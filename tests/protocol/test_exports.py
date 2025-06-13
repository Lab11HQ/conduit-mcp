import conduit.protocol as protocol


def test_all_exports_are_importable():
    """Ensure all types listed in __all__ can actually be imported."""
    for type_name in protocol.__all__:
        # This will raise AttributeError if the type isn't actually exported
        assert hasattr(protocol, type_name), (
            f"{type_name} is in __all__ but not importable"
        )


def test_key_types_are_available():
    """Smoke test that key types are available at the package level."""
    # Test a few representative types from each category
    assert protocol.Request
    assert protocol.CallToolRequest
    assert protocol.TextContent
    assert protocol.ClientRequest
    assert protocol.JSONRPCRequest
