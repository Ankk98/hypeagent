"""Validate engagement config against connector capabilities."""

from __future__ import annotations

from hypeagent.config.schema import HypeagentConfig
from hypeagent.models.action import ActionTargetKind
from hypeagent.platforms.base import PlatformCapabilities

_TARGET_NAME_TO_KIND = {
    "content": ActionTargetKind.CONTENT,
    "comment": ActionTargetKind.COMMENT,
}


def validate_engagement_against_capabilities(
    config: HypeagentConfig,
    capabilities: PlatformCapabilities,
) -> list[str]:
    """
    Return human-readable errors when engagement config exceeds connector caps.

    Fail closed: reactions quota or engagement.reactions.enabled requires
    connector.reactions, and config types/targets must be subsets of caps.
    """
    errors: list[str] = []
    if not config.reactions_requested():
        return errors

    reaction_caps = capabilities.reactions
    if reaction_caps is None:
        errors.append(
            "reactions enabled (per_agent.reactions > 0 or engagement.reactions.enabled) "
            "but connector does not advertise capabilities().reactions"
        )
        return errors

    reaction_cfg = config.engagement.reactions
    allowed_targets = reaction_caps.target_kinds
    for target_name in reaction_cfg.targets:
        kind = _TARGET_NAME_TO_KIND[target_name]
        if kind not in allowed_targets:
            errors.append(
                f"engagement.reactions.targets includes {target_name!r} but connector "
                f"only supports: {sorted(k.value for k in allowed_targets)}"
            )

    if reaction_cfg.types is not None:
        unknown = sorted(set(reaction_cfg.types) - set(reaction_caps.allowed_types))
        if unknown:
            allowed = ", ".join(sorted(reaction_caps.allowed_types))
            errors.append(
                f"engagement.reactions.types not supported by connector: {', '.join(unknown)} "
                f"(allowed: {allowed})"
            )

    if reaction_cfg.weights:
        weight_keys = set(reaction_cfg.weights)
        allowed_weight_types = set(reaction_caps.allowed_types)
        if reaction_cfg.types is not None:
            allowed_weight_types &= set(reaction_cfg.types)
        unknown_weights = sorted(weight_keys - allowed_weight_types)
        if unknown_weights:
            errors.append(
                "engagement.reactions.weights keys not in allowed types: "
                + ", ".join(unknown_weights)
            )

    return errors
