from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Greek letter tables
# ---------------------------------------------------------------------------
GREEK_TO_TOKEN: dict[str, str] = {
    "alpha":   "ALPHA",   "beta":    "BETA",    "gamma":   "GAMMA",
    "delta":   "DELTA",   "epsilon": "EPSILON", "zeta":    "ZETA",
    "eta":     "ETA",     "theta":   "THETA",   "iota":    "IOTA",
    "kappa":   "KAPPA",   "lambda":  "LAMBDA",  "mu":      "MU",
    "nu":      "NU",      "xi":      "XI",      "pi":      "PI",
    "rho":     "RHO",     "sigma":   "SIGMA",   "tau":     "TAU",
    "upsilon": "UPSILON", "phi":     "PHI",     "chi":     "CHI",
    "psi":     "PSI",     "omega":   "OMEGA",
    "Gamma":   "GAMMA",   "Delta":   "DELTA",   "Theta":   "THETA",
    "Lambda":  "LAMBDA",  "Xi":      "XI",      "Pi":      "PI",
    "Sigma":   "SIGMA",   "Upsilon": "UPSILON", "Phi":     "PHI",
    "Psi":     "PSI",     "Omega":   "OMEGA",
}

UNICODE_GREEK: dict[str, str] = {
    'α': 'ALPHA',   'β': 'BETA',    'γ': 'GAMMA',
    'δ': 'DELTA',   'ε': 'EPSILON', 'ζ': 'ZETA',
    'η': 'ETA',     'θ': 'THETA',   'ι': 'IOTA',
    'κ': 'KAPPA',   'λ': 'LAMBDA',  'μ': 'MU',
    'ν': 'NU',      'ξ': 'XI',      'π': 'PI',
    'ρ': 'RHO',     'σ': 'SIGMA',   'τ': 'TAU',
    'υ': 'UPSILON', 'φ': 'PHI',     'χ': 'CHI',
    'ψ': 'PSI',     'ω': 'OMEGA',
    'Γ': 'GAMMA',   'Δ': 'DELTA',   'Θ': 'THETA',
    'Λ': 'LAMBDA',  'Ξ': 'XI',      'Π': 'PI',
    'Σ': 'SIGMA',   'Υ': 'UPSILON', 'Φ': 'PHI',
    'Ψ': 'PSI',     'Ω': 'OMEGA',
}

# ---------------------------------------------------------------------------
# Unicode math operators
# PyMuPDF outputs these unicode symbols instead of LaTeX commands.
# Mapped to the same tokens as the LaTeX path so query and dataset
# embeddings stay aligned.
# ---------------------------------------------------------------------------

UNICODE_MATH_OPS: dict[str, str] = {
    '∑': 'SUM',         # sum sign
    '∫': 'INT',         # integral
    '∬': 'INT',         # double integral
    '∭': 'INT',         # triple integral
    '∮': 'INT',         # contour integral
    '∏': 'PROD',        # n-ary product
    '∂': 'PARTIAL',     # partial differential
    '∇': 'NABLA',       # nabla
    'ℏ': 'HBAR',        # planck constant / 2pi
    '∞': 'INF',         # infinity
    '√': 'SQRT',        # square root
    '×': 'TIMES',       # multiplication sign
    '·': 'DOT',         # middle dot
    '⋅': 'DOT',         # dot operator
    '±': 'PLUSMINUS',   # plus-minus sign
    '∓': 'PLUSMINUS',   # minus-or-plus sign
    '≤': 'LEQ',         # less-than or equal to
    '≥': 'GEQ',         # greater-than or equal to
    '≠': 'NEQ',         # not equal to
    '≈': 'APPROX',      # almost equal to
    '∼': 'APPROX',      # tilde operator
    '≡': 'EQUIV',       # identical to
    '∝': 'PROPTO',      # proportional to
    '→': 'RIGHTARROW',  # rightwards arrow
    '←': 'LEFTARROW',   # leftwards arrow
    '↔': 'LEFTRIGHTARROW',
    '⇒': 'IMPLIES',     # rightwards double arrow
    '⇔': 'IFF',         # left right double arrow
    '⟨': '(',           # mathematical left angle bracket
    '⟩': ')',           # mathematical right angle bracket
    '⟪': '(',           # left double angle bracket
    '⟫': ')',           # right double angle bracket
    '∈': 'IN',          # element of
    '∉': 'NOTIN',       # not an element of
    '⊂': 'SUBSET',      # subset of
    '⊃': 'SUPSET',      # superset of
    '⊆': 'SUBSET',      # subset of or equal to
    '⊇': 'SUPSET',      # superset of or equal to
    '∩': 'INTERSECT',   # intersection
    '∪': 'UNION',       # union
    '∀': 'FORALL',      # for all
    '∃': 'EXISTS',      # there exists
    '¬': 'NOT',         # not sign
    '⊗': 'TENSOR',      # circled times
    '⊕': 'OPLUS',       # circled plus
    '†': 'DAGGER',      # dagger
    '‡': 'DDAGGER',     # double dagger
    '…': '...',         # horizontal ellipsis
}

# Unicode super/subscript digits
# PyMuPDF renders x^2 as x², not x^{2}.
# Map to the same ^(n)/_(n) form the LaTeX path produces for \^{n}.
SUPERSCRIPT_DIGITS: dict[str, str] = {
    '⁰': '^(0)', '¹': '^(1)', '²': '^(2)', '³': '^(3)',
    '⁴': '^(4)', '⁵': '^(5)', '⁶': '^(6)', '⁷': '^(7)',
    '⁸': '^(8)', '⁹': '^(9)',
    '⁺': '^(+)', '⁻': '^(-)', '⁼': '^(=)',
    '⁽': '^(()', '⁾': '^())',
    'ⁿ': '^(n)', 'ⁱ': '^(i)',
}

SUBSCRIPT_DIGITS: dict[str, str] = {
    '₀': '_(0)', '₁': '_(1)', '₂': '_(2)', '₃': '_(3)',
    '₄': '_(4)', '₅': '_(5)', '₆': '_(6)', '₇': '_(7)',
    '₈': '_(8)', '₉': '_(9)',
    '₊': '_(+)', '₋': '_(-)', '₌': '_(=)',
    '₍': '_(()', '₎': '_()',
    'ₙ': '_(n)', 'ᵢ': '_(i)', 'ⱼ': '_(j)', 'ₖ': '_(k)',
}


# ---------------------------------------------------------------------------
# Main normalisation function
# ---------------------------------------------------------------------------
def normalize_text_for_fingerprint(text: str) -> str:
    """
    Normalise academic text for fingerprinting / similarity comparison.

    Steps:
      1.  LaTeX Greek commands   -> uppercase tokens   (\\alpha  -> ALPHA)
      2a. Unicode Greek letters  -> uppercase tokens   (alpha -> ALPHA via unicode)
      2b. Unicode math ops       -> tokens             (chr 2211 -> SUM)
      2c. Unicode super/sub      -> ^(n) / _(n)        (x2 -> x^(2))
      3.  LaTeX math constructs  -> readable tokens    (\\frac{a}{b} -> FRAC(a,b))
      4.  Named math operators   -> uppercase tokens   (\\sum_{i} -> SUM)
      5.  Physical constants     -> tokens             (\\hbar -> HBAR)
      6.  Relational operators   -> tokens             (\\leq -> LEQ)
      7.  German umlaut macros   -> actual umlauts
      8.  Remaining LaTeX macros stripped
      9.  LaTeX delimiters stripped                    ({ } [ ] $)
      10. Lowercase + collapse whitespace

    Note: steps 4-6 use (?![a-zA-Z]) instead of \\b so that commands
    followed by _ or ^ subscript/superscript markers still match, e.g.
    \\sum_{i} and \\partial_{x}.
    """
    # 1. LaTeX Greek command sequences
    for name, token in GREEK_TO_TOKEN.items():
        text = re.sub(rf'\\{name}\b', token, text)

    # 2a. Unicode Greek characters
    for char, token in UNICODE_GREEK.items():
        text = text.replace(char, token)

    # 2b. Unicode math operators (PyMuPDF produces these instead of LaTeX)
    for char, token in UNICODE_MATH_OPS.items():
        text = text.replace(char, f' {token} ')

    # 2c. Unicode super/subscript digits
    for char, token in SUPERSCRIPT_DIGITS.items():
        text = text.replace(char, token)
    for char, token in SUBSCRIPT_DIGITS.items():
        text = text.replace(char, token)

    # 3. Common math constructs (run before step 4 so _{...} -> _(...) first)
    text = re.sub(r'\\frac\{([^{}]*)\}\{([^{}]*)\}', r'FRAC(\1,\2)', text)
    text = re.sub(r'\\sqrt\{([^{}]*)\}',              r'SQRT(\1)',     text)
    text = re.sub(r'\^\{([^{}]*)\}',                  r'^(\1)',        text)
    text = re.sub(r'_\{([^{}]*)\}',                   r'_(\1)',        text)

    # 4. Named math operators
    # Use (?![a-zA-Z]) not \b — underscore is \w so \b misses \sum_{i}.
    text = re.sub(
        r'\\(sum|int|prod|lim|sup|inf)(?![a-zA-Z])',
        lambda m: m.group(1).upper(),
        text,
    )
    text = re.sub(
        r'\\(exp|log|ln|sin|cos|tan)(?![a-zA-Z])',
        lambda m: m.group(1).upper(),
        text,
    )

    # 5. Physical constants
    text = re.sub(r'\\hbar(?![a-zA-Z])',    'HBAR',      text)
    text = re.sub(r'\\infty(?![a-zA-Z])',   'INF',       text)
    text = re.sub(r'\\partial(?![a-zA-Z])', 'PARTIAL',   text)
    text = re.sub(r'\\nabla(?![a-zA-Z])',   'NABLA',     text)
    text = re.sub(r'\\times(?![a-zA-Z])',   'TIMES',     text)
    text = re.sub(r'\\cdot(?![a-zA-Z])',    'DOT',       text)

    # 6. Relational operators
    text = re.sub(r'\\pm(?![a-zA-Z])',     'PLUSMINUS', text)
    text = re.sub(r'\\leq(?![a-zA-Z])',    'LEQ',       text)
    text = re.sub(r'\\geq(?![a-zA-Z])',    'GEQ',       text)
    text = re.sub(r'\\neq(?![a-zA-Z])',    'NEQ',       text)
    text = re.sub(r'\\approx(?![a-zA-Z])', 'APPROX',    text)

    # 7. German umlaut macros
    text = re.sub(
        r'\\\"([aouAOU])',
        lambda m: m.group(1).translate(str.maketrans('aouAOU', '\xe4\xf6\xfc\xc4\xd6\xdc')),
        text,
    )

    # 8. Strip remaining LaTeX commands
    text = re.sub(r'\\[a-zA-Z]+\*?\s*', ' ', text)

    # 9. Strip LaTeX delimiters
    text = re.sub(r'[{}\[\]$]', ' ', text)

    # 10. Lowercase + collapse whitespace
    text = text.lower()
    text = re.sub(r'\s+', ' ', text).strip()

    return text
