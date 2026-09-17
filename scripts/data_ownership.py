"""Validate and render the provider-neutral data ownership contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "config" / "data-ownership.toml"
DEFAULT_DOCUMENT = REPO_ROOT / "docs" / "data-ownership.md"
REQUIRED_CLASSES = {"raw", "derived", "artifact", "scratch", "quarantine", "logs"}
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
CONTACT_PATTERN = re.compile(r"^[a-z][a-z0-9+.-]*:\S+$")
ALLOWED_ACTOR_KINDS = {"automation", "external", "human", "workload"}
POSITIVE_DAY_FIELDS = {
    "delete_after_days",
    "noncurrent_minimum_days",
    "review_after_days",
    "transition_after_days",
}


class OwnershipError(ValueError):
    """Raised when the ownership manifest violates its schema or invariants."""


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OwnershipError(f"{path} must be a table")
    return value


def _text(mapping: dict[str, Any], key: str, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OwnershipError(f"{path}.{key} must be a non-empty string")
    return value


def _ids(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise OwnershipError(f"{path} must be a list of IDs")
    if len(value) != len(set(value)):
        raise OwnershipError(f"{path} must not contain duplicates")
    return value


def load_contract(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            contract = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise OwnershipError(f"could not read {path}: {exc}") from None
    validate_contract(contract)
    return contract


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("schema_version") != 1:
        raise OwnershipError("schema_version must be 1")
    contract_id = _text(contract, "contract_id", "contract")
    if not ID_PATTERN.fullmatch(contract_id.replace("-", "_")):
        raise OwnershipError("contract_id must contain only lowercase letters, digits, and hyphens")
    _text(contract, "description", "contract")
    review_cycle = contract.get("review_cycle_days")
    if (
        not isinstance(review_cycle, int)
        or isinstance(review_cycle, bool)
        or not 1 <= review_cycle <= 3650
    ):
        raise OwnershipError("review_cycle_days must be a whole number from 1 to 3650")

    groups = _mapping(contract.get("groups"), "groups")
    if not groups:
        raise OwnershipError("groups must define at least one accountable group")
    for group_id, raw_group in groups.items():
        if not ID_PATTERN.fullmatch(group_id):
            raise OwnershipError(f"groups.{group_id} is not a valid ID")
        group = _mapping(raw_group, f"groups.{group_id}")
        _text(group, "display_name", f"groups.{group_id}")
        contact = _text(group, "contact", f"groups.{group_id}")
        if not CONTACT_PATTERN.fullmatch(contact):
            raise OwnershipError(f"groups.{group_id}.contact must be a scheme:value reference")
        _text(group, "responsibility", f"groups.{group_id}")

    governance = _mapping(contract.get("governance"), "governance")
    owner = _text(governance, "contract_owner_group", "governance")
    approvers = _ids(governance.get("change_approver_groups"), "governance.change_approver_groups")
    _text(governance, "exception_process", "governance")
    for group_id in [owner, *approvers]:
        if group_id not in groups:
            raise OwnershipError(f"governance references unknown group {group_id!r}")

    locations = _mapping(contract.get("locations"), "locations")
    if not locations:
        raise OwnershipError("locations must define at least one storage boundary")
    for location_id, raw_location in locations.items():
        if not ID_PATTERN.fullmatch(location_id):
            raise OwnershipError(f"locations.{location_id} is not a valid ID")
        location_config = _mapping(raw_location, f"locations.{location_id}")
        _text(location_config, "description", f"locations.{location_id}")
        _text(location_config, "terraform_output", f"locations.{location_id}")

    actors = _mapping(contract.get("actors"), "actors")
    if not actors:
        raise OwnershipError("actors must define at least one access identity")
    for actor_id, raw_actor in actors.items():
        if not ID_PATTERN.fullmatch(actor_id):
            raise OwnershipError(f"actors.{actor_id} is not a valid ID")
        actor = _mapping(raw_actor, f"actors.{actor_id}")
        _text(actor, "display_name", f"actors.{actor_id}")
        kind = _text(actor, "kind", f"actors.{actor_id}")
        if kind not in ALLOWED_ACTOR_KINDS:
            raise OwnershipError(
                f"actors.{actor_id}.kind must be one of {sorted(ALLOWED_ACTOR_KINDS)}"
            )
        _text(actor, "identity_contract", f"actors.{actor_id}")
        _text(actor, "access_semantics", f"actors.{actor_id}")

    classes = contract.get("classes")
    if not isinstance(classes, list) or not classes:
        raise OwnershipError("classes must be a non-empty array of tables")
    seen_ids: set[str] = set()
    boundaries: list[tuple[str, str, str]] = []
    for index, raw_class in enumerate(classes):
        path = f"classes[{index}]"
        data_class = _mapping(raw_class, path)
        class_id = _text(data_class, "id", path)
        if not ID_PATTERN.fullmatch(class_id):
            raise OwnershipError(f"{path}.id is not a valid ID")
        if class_id in seen_ids:
            raise OwnershipError(f"duplicate data class {class_id!r}")
        seen_ids.add(class_id)
        _text(data_class, "display_name", path)
        class_location = _text(data_class, "location", path)
        if class_location not in locations:
            raise OwnershipError(f"{path}.location references unknown location {class_location!r}")
        prefix = data_class.get("prefix")
        if not isinstance(prefix, str):
            raise OwnershipError(f"{path}.prefix must be a string")
        if prefix.startswith("/") or ".." in prefix.split("/") or "//" in prefix:
            raise OwnershipError(f"{path}.prefix must be a safe relative object prefix")
        if prefix and not prefix.endswith("/"):
            raise OwnershipError(f"{path}.prefix must end in '/' when it is not empty")
        boundaries.append((class_id, class_location, prefix))
        for field in ("owner_group", "steward_group"):
            group_id = _text(data_class, field, path)
            if group_id not in groups:
                raise OwnershipError(f"{path}.{field} references unknown group {group_id!r}")
        _text(data_class, "classification", path)
        readers = _ids(data_class.get("readers"), f"{path}.readers")
        writers = _ids(data_class.get("writers"), f"{path}.writers")
        if not writers:
            raise OwnershipError(f"{path}.writers must identify at least one actor")
        for actor_id in [*readers, *writers]:
            if actor_id not in actors:
                raise OwnershipError(f"{path} references unknown actor {actor_id!r}")

        retention = _mapping(data_class.get("retention"), f"{path}.retention")
        _text(retention, "policy", f"{path}.retention")
        _text(retention, "summary", f"{path}.retention")
        for field in POSITIVE_DAY_FIELDS:
            if field in retention:
                days = retention[field]
                if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
                    raise OwnershipError(
                        f"{path}.retention.{field} must be a positive whole number"
                    )

        recovery = _mapping(data_class.get("recovery"), f"{path}.recovery")
        if not isinstance(recovery.get("required"), bool):
            raise OwnershipError(f"{path}.recovery.required must be true or false")
        _text(recovery, "method", f"{path}.recovery")
        _text(recovery, "expectation", f"{path}.recovery")
        _text(recovery, "test_frequency", f"{path}.recovery")

    missing = REQUIRED_CLASSES - seen_ids
    if missing:
        raise OwnershipError(f"missing required data classes: {', '.join(sorted(missing))}")
    for index, (left_id, left_location, left_prefix) in enumerate(boundaries):
        for right_id, right_location, right_prefix in boundaries[index + 1 :]:
            if left_location != right_location:
                continue
            if (
                not left_prefix
                or not right_prefix
                or left_prefix.startswith(right_prefix)
                or right_prefix.startswith(left_prefix)
            ):
                raise OwnershipError(
                    f"data classes {left_id!r} and {right_id!r} overlap "
                    f"in location {left_location!r}"
                )


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _actor_list(values: list[str]) -> str:
    return ", ".join(f"`{value}`" for value in values) if values else "None"


def render_markdown(contract: dict[str, Any], source: str = "config/data-ownership.toml") -> str:
    governance = contract["governance"]
    groups = contract["groups"]
    locations = contract["locations"]
    actors = contract["actors"]
    lines = [
        "# Data ownership contract",
        "",
        (
            f"> Generated from `{source}`. Edit the manifest and run "
            "`make ownership-render`; do not edit this file directly."
        ),
        "",
        _cell(contract["description"]),
        "",
        f"Contract ID: `{contract['contract_id']}`  ",
        f"Schema version: `{contract['schema_version']}`  ",
        f"Review cycle: every {contract['review_cycle_days']} days  ",
        f"Contract owner: `{governance['contract_owner_group']}`  ",
        f"Change approvers: {_actor_list(governance['change_approver_groups'])}  ",
        (
            f"Exception process: [{governance['exception_process']}]"
            f"(../{governance['exception_process']})"
        ),
        "",
        "## Accountable groups",
        "",
        (
            "Group IDs are stable policy references. Deployments may change their display names "
            "and contact routes without changing workload identities or object prefixes."
        ),
        "",
        "| Group ID | Display name | Contact | Responsibility |",
        "|---|---|---|---|",
    ]
    for group_id, group in groups.items():
        lines.append(
            f"| `{group_id}` | {_cell(group['display_name'])} | "
            f"`{_cell(group['contact'])}` | {_cell(group['responsibility'])} |"
        )
    lines.extend(
        [
            "",
            "## Storage locations",
            "",
            "| Location | Terraform contract | Purpose |",
            "|---|---|---|",
        ]
    )
    for location_id, location in locations.items():
        lines.append(
            f"| `{location_id}` | `{location['terraform_output']}` | "
            f"{_cell(location['description'])} |"
        )
    lines.extend(
        [
            "",
            "## Access actors",
            "",
            (
                "These are logical identities mapped to provider-specific service accounts or "
                "roles by Terraform. Human owners approve policy; workloads receive data-plane "
                "access."
            ),
            "",
            "| Actor | Kind | Identity contract | Access semantics |",
            "|---|---|---|---|",
        ]
    )
    for actor_id, actor in actors.items():
        lines.append(
            f"| `{actor_id}` — {_cell(actor['display_name'])} | `{actor['kind']}` | "
            f"`{actor['identity_contract']}` | {_cell(actor['access_semantics'])} |"
        )
    lines.extend(
        [
            "",
            "## Ownership matrix",
            "",
            "| Class | Boundary | Owner / steward | Writers | Readers | Retention | Recovery |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for data_class in contract["classes"]:
        prefix = data_class["prefix"] or "<entire location>"
        boundary = f"`{data_class['location']}:{prefix}`"
        owner = f"`{data_class['owner_group']}` / `{data_class['steward_group']}`"
        recovery = data_class["recovery"]
        recovery_label = "Required" if recovery["required"] else "Best effort"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{data_class['id']}`",
                    boundary,
                    owner,
                    _actor_list(data_class["writers"]),
                    _actor_list(data_class["readers"]),
                    _cell(data_class["retention"]["summary"]),
                    f"{recovery_label}: {_cell(recovery['expectation'])}",
                ]
            )
            + " |"
        )
    lines.extend(["", "## Class details", ""])
    for data_class in contract["classes"]:
        retention = data_class["retention"]
        recovery = data_class["recovery"]
        lines.extend(
            [
                f"### {data_class['display_name']} (`{data_class['id']}`)",
                "",
                f"- Classification: `{data_class['classification']}`",
                (
                    f"- Accountable owner: `{data_class['owner_group']}`; operational steward: "
                    f"`{data_class['steward_group']}`"
                ),
                (
                    f"- Writers: {_actor_list(data_class['writers'])}; readers: "
                    f"{_actor_list(data_class['readers'])}"
                ),
                f"- Retention policy: `{retention['policy']}` — {_cell(retention['summary'])}",
                f"- Recovery method: `{recovery['method']}` — {_cell(recovery['expectation'])}",
                f"- Recovery validation: `{recovery['test_frequency']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Changing ownership",
            "",
            "1. Edit group contacts or class assignments in `config/data-ownership.toml`.",
            "2. Obtain approval from the configured contract owner and change-approver groups.",
            "3. Run `make ownership-render` and review both the manifest and generated document.",
            (
                "4. If readers, writers, locations, or prefixes changed, update and apply the "
                "matching Terraform IAM contract before data moves."
            ),
            (
                "5. Run `make ownership-check`; CI rejects invalid references, overlapping "
                "prefixes, missing required classes, and stale generated documentation."
            ),
            "",
            (
                "Group ownership does not itself grant cloud access. Access remains attached to "
                "the workload identities named above, so changing an accountable group cannot "
                "silently expand data-plane permissions."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _source_label(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "export-json", "render", "validate"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--document", type=Path, default=DEFAULT_DOCUMENT)
    args = parser.parse_args(argv)

    try:
        contract = load_contract(args.manifest)
        rendered = render_markdown(contract, _source_label(args.manifest))
        if args.action == "validate":
            print(f"valid ownership contract: {args.manifest}")
        elif args.action == "export-json":
            print(json.dumps(contract, indent=2, sort_keys=True))
        elif args.action == "render":
            args.document.parent.mkdir(parents=True, exist_ok=True)
            args.document.write_text(rendered)
            print(f"rendered ownership document: {args.document}")
        else:
            try:
                current = args.document.read_text()
            except OSError:
                raise OwnershipError(
                    f"generated document is missing: {args.document}; run the render action"
                ) from None
            if current != rendered:
                raise OwnershipError(
                    f"generated document is stale: {args.document}; run the render action"
                )
            print(f"ownership contract and generated document are current: {args.manifest}")
    except OwnershipError as exc:
        print(f"data ownership validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
