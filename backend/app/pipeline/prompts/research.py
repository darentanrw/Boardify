"""Stage 1 prompt templates for Perplexity rules research."""

RESEARCH_SYSTEM = """You are a board game rules researcher. Extract COMPLETE, PRECISE rules.
Do NOT summarize or simplify. Include exact card counts, exact turn sequences, and all edge cases."""


RESEARCH_USER = """Research the card game "{game_name}" and provide COMPLETE rules in these exact sections:

## DECK COMPOSITION
- Every distinct card type
- Exact count of each type
- Card properties (suit, color, rank, value, special attributes)
- Cards with dynamic count based on player number (e.g. Exploding Kittens = players - 1)

## GAME ZONES
- All areas where cards exist (draw pile, discard pile, hands, melds, community cards, pot, etc.)
- How many cards are visible in each zone and to whom
- What happens when a zone is empty

## TURN STRUCTURE
- List every phase of a turn in order
- What the active player MUST do and what they MAY do in each phase
- Can multiple cards be played per turn? Is there a mandatory action (e.g. must draw)?

## CARD EFFECTS
- What happens when each card type is played/revealed
- Special interactions between card types
- Cards that trigger on DRAW rather than on PLAY

## COMBO / MULTI-CARD PLAYS
- Can multiple cards be played together as a combo?
- What combinations are valid (pairs, triples, N-of-a-kind, N-different)?
- What does each combo do?

## INTERRUPT / REACTION MECHANICS
- Can any card be played OUT OF TURN to cancel or counter another card?
- Can interrupts be chained (e.g. counter the counter)?
- What is the timing window for reactions?

## PLAYER TARGETING
- Do any cards require choosing another player as a target?
- What happens when a player is targeted? (steal, give, reveal, etc.)

## PLAYER ELIMINATION
- Can players be eliminated mid-game?
- What triggers elimination?
- How does the game handle eliminated players (turn order, win condition)?

## WIN CONDITION
- How the game ends
- How the winner is determined (last alive, highest score, empty hand, etc.)
- Scoring rules if applicable

## SPECIAL MECHANICS
- Betting, asking for cards, challenging, slapping, melding, etc.
- Penalty rules
- Any mechanics involving inserting cards at a specific position in a deck

Be exhaustive. Missing a rule means the game will be broken."""
