"""The Salubrious Philosopher's printed-Oracle categories, independent of deck roles."""
import re


_PERMANENT = re.compile(r"\b(?:creatures?|artifacts?|enchantments?|lands?|permanents?|planeswalkers?|battles?|auras?|equipment|vehicles?|tokens?)\b")
_MANA = re.compile(r"\badds?\s+(?:[a-z0-9]+\s+)*(?:\{[wubrgcsxyz0-9][^}]*\}|mana\b)")


def _text(card):
    text = (card.oracle_text or "").lower().replace("’", "'")
    # Reminder text describes rules; it isn't another ability of the card.
    while re.search(r"\([^()]*\)", text):
        text = re.sub(r"\([^()]*\)", "", text)
    return text


def _opposing_permanent(body, antecedent=""):
    body = body.split(" except ", 1)[0]
    if (re.match(r"(?:that|those)\b", body) and re.search(r"\bcreates?\b", antecedent)
            and not re.search(r"\b(?:opponent|target (?:creature|artifact|enchantment|land|permanent))\b", antecedent)):
        return False  # Exiling the spell's own created token is not opposing removal.
    # The removal instruction must affect a battlefield object, not a card
    # in a graveyard/hand/library or a spell on the stack.
    if re.search(r"\b(?:cards?|spells?)\b", body) and not re.search(r"\b(?:or|and)\b", body):
        return False
    if re.search(r"\bfrom (?:an? |the |your |any |all |target |each |their |opponents?[\']? )*(?:graveyards?|hands?|libraries|library|exile)\b", body):
        return False
    if not _PERMANENT.search(body) and "any target" not in body and not re.search(r"\btargets\b", body):
        if re.search(r"\b(?:itself|it|them|each other)\b", body):
            return _opposing_permanent(antecedent)
        return False
    for recipient in re.split(r"\band\s+(?=(?:target|each|all|another)\b)|\bor\s+(?=target\b)", body):
        if not (_PERMANENT.search(recipient) or "any target" in recipient or re.search(r"\btargets\b", recipient)):
            continue
        if re.search(r"\b(?:creature|artifact|enchantment|land|permanent) cards?\b", recipient):
            continue
        if re.search(r"\byou (?:control|own)\b", recipient) and not re.search(r"\byou (?:don't|do not) (?:control|own)\b", recipient):
            continue
        return True
    return False


def matches(card, kind):
    text = _text(card)
    if kind == "win_condition":
        # Printed mana value, including X=0 outside the stack; no alternative costs.
        return (card.converted_mana_cost or 0) >= 6
    if kind == "mana_base":
        type_line = (card.type_line or "").lower()
        basic_mana = re.search(r"\bland\b", type_line) and re.search(r"\b(?:plains|island|swamp|mountain|forest)\b", type_line)
        return bool(basic_mana or _MANA.search(text))
    if kind != "removal" or not (card.is_instant or card.is_sorcery):
        return False
    # Read every printed conditional/modal instruction, regardless of whether
    # it can currently be chosen, paid for, or resolved on this battlefield.
    for instruction in re.finditer(r"\b(?:destroys?|exiles?)\s+([^.;\n]+)", text):
        if _opposing_permanent(instruction.group(1), text[:instruction.start()]):
            return True
    for instruction in re.finditer(r"\bdeals?\s+[^.;\n]*?\bdamage (?:to\s+|divided[^.;\n]*?among\s+)([^.;\n]+)", text):
        prefix = text[max(0, instruction.start() - 8):instruction.start()]
        if not re.search(r"\bwould\s*$", prefix) and _opposing_permanent(instruction.group(1), text[:instruction.start()]):
            return True
    # Fighting is a printed damage instruction even though Oracle abbreviates
    # its rules action instead of spelling out "deal damage".
    for instruction in re.finditer(r"\bfights?\s+([^.;\n]+)", text):
        if _opposing_permanent(instruction.group(1), text[:instruction.start()]):
            return True
    return False
