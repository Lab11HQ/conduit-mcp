import re


def matches_template(uri: str, template: str) -> bool:
    """Check if a URI matches a URI template pattern.

    Supports basic RFC 6570 variable substitution like {var}.
    Returns True if the URI could have been generated from this template.
    """
    # Convert template to regex pattern
    # Replace {variable} with regex group that matches non-slash characters
    pattern = re.escape(template)
    pattern = re.sub(r"\\{[^}]+\\}", r"([^/]+)", pattern)
    pattern = f"^{pattern}$"

    return bool(re.match(pattern, uri))


def extract_template_variables(uri: str, template: str) -> dict[str, str]:
    """Extract variable values from a URI using a template.

    Returns a dict mapping variable names to their values.
    """
    # Find variable names in template
    var_names = re.findall(r"{([^}]+)}", template)

    # Convert template to regex with named groups
    pattern = re.escape(template)
    for var_name in var_names:
        pattern = pattern.replace(f"\\{{{var_name}\\}}", f"(?P<{var_name}>[^/]+)")
    pattern = f"^{pattern}$"

    match = re.match(pattern, uri)
    if match:
        return match.groupdict()
    return {}
