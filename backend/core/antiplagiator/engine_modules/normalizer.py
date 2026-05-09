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
    # Upper-case variants
    "Gamma":   "GAMMA",   "Delta":   "DELTA",   "Theta":   "THETA",
    "Lambda":  "LAMBDA",  "Xi":      "XI",      "Pi":      "PI",
    "Sigma":   "SIGMA",   "Upsilon": "UPSILON", "Phi":     "PHI",
    "Psi":     "PSI",     "Omega":   "OMEGA",
}

UNICODE_GREEK: dict[str, str] = {
    'α': 'ALPHA',   'β': 'BETA',    'γ': 'GAMMA',   'δ': 'DELTA',
    'ε': 'EPSILON', 'ζ': 'ZETA',    'η': 'ETA',     'θ': 'THETA',
    'ι': 'IOTA',    'κ': 'KAPPA',   'λ': 'LAMBDA',  'μ': 'MU',
    'ν': 'NU',      'ξ': 'XI',      'π': 'PI',      'ρ': 'RHO',
    'σ': 'SIGMA',   'τ': 'TAU',     'υ': 'UPSILON', 'φ': 'PHI',
    'χ': 'CHI',     'ψ': 'PSI',     'ω': 'OMEGA',
    'Γ': 'GAMMA',   'Δ': 'DELTA',   'Θ': 'THETA',   'Λ': 'LAMBDA',
    'Ξ': 'XI',      'Π': 'PI',      'Σ': 'SIGMA',   'Υ': 'UPSILON',
    'Φ': 'PHI',     'Ψ': 'PSI',     'Ω': 'OMEGA',
}

# ---------------------------------------------------------------------------
# Main normalisation function
# ---------------------------------------------------------------------------

def normalize_text_for_fingerprint(text: str) -> str:
    """
    Normalise academic text for fingerprinting / similarity comparison.

    Steps (in order):
      1. LaTeX Greek commands  → uppercase tokens  (\\alpha → ALPHA)
      2. Unicode Greek letters → uppercase tokens  (α → ALPHA)
      3. Common math constructs → readable tokens  (\\frac{a}{b} → FRAC(a,b))
      4. Named math operators  → uppercase tokens  (\\sum → SUM)
      5. Physical constants    → tokens            (\\hbar → HBAR)
      6. Relational operators  → tokens            (\\leq → LEQ)
      7. German umlaut macros  → actual umlauts    (\\"a → ä)
      8. Remaining LaTeX macros stripped
      9. LaTeX delimiters stripped                 ({ } [ ] $)
     10. Lowercase + collapse whitespace
    """
    # 1. LaTeX Greek command sequences
    for name, token in GREEK_TO_TOKEN.items():
        text = re.sub(rf'\\{name}\b', token, text)

    # 2. Unicode Greek characters
    for char, token in UNICODE_GREEK.items():
        text = text.replace(char, token)

    # 3. Common math constructs
    text = re.sub(r'\\frac\{([^{}]*)\}\{([^{}]*)\}', r'FRAC(\1,\2)', text)
    text = re.sub(r'\\sqrt\{([^{}]*)\}',              r'SQRT(\1)',     text)
    text = re.sub(r'\^\{([^{}]*)\}',                  r'^(\1)',        text)
    text = re.sub(r'_\{([^{}]*)\}',                   r'_(\1)',        text)

    # 4. Named math operators
    text = re.sub(
        r'\\(sum|int|prod|lim|sup|inf)\b',
        lambda m: m.group(1).upper(),
        text,
    )
    text = re.sub(
        r'\\(exp|log|ln|sin|cos|tan)\b',
        lambda m: m.group(1).upper(),
        text,
    )

    # 5. Physical constants
    text = re.sub(r'\\hbar\b',    'HBAR',      text)
    text = re.sub(r'\\infty\b',   'INF',       text)
    text = re.sub(r'\\partial\b', 'PARTIAL',   text)
    text = re.sub(r'\\nabla\b',   'NABLA',     text)
    text = re.sub(r'\\times\b',   'TIMES',     text)
    text = re.sub(r'\\cdot\b',    'DOT',       text)

    # 6. Relational operators
    text = re.sub(r'\\pm\b',     'PLUSMINUS', text)
    text = re.sub(r'\\leq\b',    'LEQ',       text)
    text = re.sub(r'\\geq\b',    'GEQ',       text)
    text = re.sub(r'\\neq\b',    'NEQ',       text)
    text = re.sub(r'\\approx\b', 'APPROX',    text)

    # 7. German umlaut macros
    text = re.sub(
        r'\\\"([aouAOU])',
        lambda m: m.group(1).translate(str.maketrans('aouAOU', 'äöüÄÖÜ')),
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