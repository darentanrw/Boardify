"""Prompt templates for two-phase DSL generation and retries."""

PLAN_SYSTEM = """You are a game architect designing a data-driven card game engine.
Given researched rules, produce a DESIGN PLAN listing every zone, variable, phase, action, and card effect needed.
Think step by step. Be exhaustive."""


PLAN_USER = """Design a game engine plan for the following card game.

## Researched Rules
{research_output}

Produce a plan with these sections:
1. ZONES: name, behavior (stack/hand_fan/spread/grid), visibility, on_draw triggers
2. VARIABLES: global vars and per-player vars with types and defaults
   - Include turns_remaining (for attack/extra-turn mechanics) and is_alive (for elimination games) if needed
3. DECK MANIFEST: all card templates with template_vars
4. TURN PHASES: ordered list (include free-play phase if players can play multiple cards)
5. ROUTINES: what happens in each phase (pseudocode using move, branch, set_global, etc.)
6. ACTIONS: what the player can do, with conditions
   - For each action: can it be interrupted? (reaction_window)
   - For each action: is it a multi-card combo? (card_count + card_match_rule)
   - For each action: can it be played out of turn? (any_phase)
7. CARD EFFECTS: what each special card does post-play
8. INTERRUPT FLOW: if the game has interrupt/reaction cards, describe the resolution stack"""


DSL_SYSTEM = """You are a JSON code generator. Convert the game plan into a valid game DSL JSON document.

## $-Reference Conventions
- $global.{key} -- read a global variable
- $player.{key} -- read current player's variable
- $card -- the card being acted on (single card actions)
- $cards -- the cards being played (multi-card combo actions)
- $card.data.{field} -- a property of that card
- $zone.{name}.top -- top card of a zone
- $zone.{name}.top.data.{field} -- property of top card
- $player.hand -- current player's hand zone
- $player.hand.count -- card count in hand
- $current_player -- reference to the acting player
- $args.{key} -- value stored earlier via store_as
- $args.target_player -- player chosen by choose_player op
- $args.target_player.hand -- target player's hand zone
- $args.drawn_card -- card stored after a move with store_as
- $args.drawn_card.data.{field} -- property of stored card

## Action Fields
- any_phase: true -- card can be played outside normal turn (Nope-style interrupts)
- reaction_window: {...} -- after this action, other players can react
- card_count: N -- how many cards this action plays (2 for pairs, 3 for triples)
- card_match_rule: "same_type" | "all_different" | null
- max_per_turn: null -- unlimited plays per turn (free play phase)

Output ONLY valid JSON. No markdown, no explanation."""


DSL_USER = """## JSON Schema (your output MUST conform to this)
{json_schema}

## Complete Working Example (Uno)
{uno_example}

## Game Design Plan
{game_plan}

Generate the complete game DSL JSON for this game."""


RETRY_USER = """The JSON you generated failed validation with these errors:

{validation_errors}

Fix ONLY the errors above. Keep everything else the same. Output the complete corrected JSON."""


CODEGEN_SYSTEM = """You are modifying a templated multiplayer card game webapp.
The template already has WebSocket infrastructure, generic card/zone/player UI components,
and a game state management shell. Your job is to wire everything up according to the DSL.

Do NOT rewrite the WebSocket layer or generic components. Only modify game-specific files."""


CODEGEN_USER = """## Game DSL (validated schema)
{dsl_json}

## Template files you may modify
{template_file_listing}

## Key template source files
{template_sources}

Wire up the game:
1. Populate deck from deck_manifest
2. Layout zones according to zones config
3. Implement FSM turn phases and routines as state transitions
4. Bind actions to UI event handlers
5. Implement card_effects as post-play hooks
6. Handle reaction_windows as interrupt UI flows (pause, show reaction prompt to other players)
7. Connect all state mutations to WebSocket broadcast

Output the modified files."""
