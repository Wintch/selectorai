"""Big block-letter font — hand-built, verified by rendering it and reading
the output before committing it here (not eyeballed blind). Covers only
the characters actually used: the title "SELECTORAI" and the provider
labels below. Each glyph is a list of 6 row-strings.
"""

FONT = {
    "A": [" ██ ", "█  █", "█  █", "████", "█  █", "█  █"],
    "C": [" ███", "█   ", "█   ", "█   ", "█   ", " ███"],
    "D": ["███ ", "█  █", "█  █", "█  █", "█  █", "███ "],
    "E": ["████", "█   ", "███ ", "█   ", "█   ", "████"],
    "G": [" ███", "█   ", "█ ██", "█  █", "█  █", " ███"],
    "I": ["████", " █  ", " █  ", " █  ", " █  ", "████"],
    "K": ["█  █", "█ █ ", "██  ", "█ █ ", "█  █", "█  █"],
    "L": ["█   ", "█   ", "█   ", "█   ", "█   ", "████"],
    "N": ["█  █", "██ █", "█ ██", "█  █", "█  █", "█  █"],
    "O": [" ██ ", "█  █", "█  █", "█  █", "█  █", " ██ "],
    "R": ["███ ", "█  █", "███ ", "█ █ ", "█  █", "█  █"],
    "S": [" ███", "█   ", " ██ ", "   █", "   █", "███ "],
    "T": ["████", " █  ", " █  ", " █  ", " █  ", " █  "],
    "U": ["█  █", "█  █", "█  █", "█  █", "█  █", " ██ "],
    "V": ["█  █", "█  █", "█  █", "█  █", " ██ ", " ██ "],
    "X": ["█  █", "█  █", " ██ ", " ██ ", "█  █", "█  █"],
    "Y": ["█  █", "█  █", " ██ ", " █  ", " █  ", " █  "],
    " ": ["  ", "  ", "  ", "  ", "  ", "  "],
}


def render_big(text):
    rows = ["" for _ in range(6)]
    for ch in text.upper():
        glyph = FONT.get(ch, FONT[" "])
        for i in range(6):
            rows[i] += glyph[i] + " "
    return [r.rstrip() for r in rows]
