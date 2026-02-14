"""Prompt templates for parsing researched markdown into ResearchedRules JSON."""

PARSE_SYSTEM = """You are a data extraction engine. Parse the game rules document
into the exact JSON schema provided. Extract every card type with its EXACT count.
If a count depends on player number, put the formula in count_rule and use the
count for a typical game (e.g. 4 players)."""


PARSE_USER = """## Raw Rules Document
{raw_rules_text}

## Output JSON Schema
{research_schema}

Parse the rules into this exact schema. Include ALL card types, ALL zones,
ALL turn phases, ALL special mechanics. Set the boolean flags (has_interrupts,
has_player_elimination, etc.) based on the rules content.

Output ONLY valid JSON."""
