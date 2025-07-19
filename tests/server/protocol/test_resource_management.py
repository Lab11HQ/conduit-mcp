from unittest.mock import AsyncMock

from conduit.protocol.resources import (
    Resource,
    ResourceTemplate,
)
from conduit.server.protocol.resources import ResourceManager


class TestGlobalResourceManagement:
    def setup_method(self):
        self.manager = ResourceManager()
        self.test_resource = Resource(uri="file:///test.txt", name="Test File")
        self.test_template = ResourceTemplate(
            uri_template="file:///logs/{date}.log", name="Log Template"
        )
        self.mock_handler = AsyncMock()

    def test_add_resource_stores_resource_and_handler(self):
        # Arrange - setup already done in setup_method

        # Act
        self.manager.add_resource(self.test_resource, self.mock_handler)

        # Assert
        # Verify resource is stored
        resources = self.manager.get_resources()
        assert "file:///test.txt" in resources
        assert resources["file:///test.txt"] == self.test_resource

        # Verify handler is stored internally
        assert "file:///test.txt" in self.manager.global_handlers
        assert self.manager.global_handlers["file:///test.txt"] == self.mock_handler

    def test_add_template_stores_template_and_handler(self):
        # Arrange - setup already done in setup_method

        # Act
        self.manager.add_template(self.test_template, self.mock_handler)

        # Assert
        # Verify template is stored
        templates = self.manager.get_templates()
        assert "file:///logs/{date}.log" in templates
        assert templates["file:///logs/{date}.log"] == self.test_template

        # Verify handler is stored internally
        assert "file:///logs/{date}.log" in self.manager.global_template_handlers
        assert (
            self.manager.global_template_handlers["file:///logs/{date}.log"]
            == self.mock_handler
        )

    def test_remove_resource_removes_resource_and_handler(self):
        # Arrange - add resource first
        self.manager.add_resource(self.test_resource, self.mock_handler)
        assert "file:///test.txt" in self.manager.global_resources
        assert "file:///test.txt" in self.manager.global_handlers

        # Act
        self.manager.remove_resource("file:///test.txt")

        # Assert
        # Verify resource is removed
        resources = self.manager.get_resources()
        assert "file:///test.txt" not in resources

        # Verify handler is removed internally
        assert "file:///test.txt" not in self.manager.global_handlers

    def test_remove_resource_silently_succeeds_for_unknown_resource(self):
        # Arrange - no resource added
        self.manager.remove_resource("file:///unknown.txt")
        assert "file:///unknown.txt" not in self.manager.global_resources
        assert "file:///unknown.txt" not in self.manager.global_handlers

        # Assert
        # Verify no change in resources
        resources = self.manager.get_resources()
        assert "file:///unknown.txt" not in resources

    def test_remove_template_removes_template_and_handler(self):
        # Arrange - add template first
        self.manager.add_template(self.test_template, self.mock_handler)
        assert "file:///logs/{date}.log" in self.manager.global_templates
        assert "file:///logs/{date}.log" in self.manager.global_template_handlers

        # Act
        self.manager.remove_template("file:///logs/{date}.log")

        # Assert
        # Verify template is removed
        templates = self.manager.get_templates()
        assert "file:///logs/{date}.log" not in templates

        # Verify handler is removed internally
        assert "file:///logs/{date}.log" not in self.manager.global_template_handlers

    def test_remove_template_silently_succeeds_for_unknown_template(self):
        # Arrange - no template added
        self.manager.remove_template("file:///unknown.log")

        # Assert
        # Verify no change in templates
        templates = self.manager.get_templates()
        assert "file:///unknown.log" not in templates
        assert "file:///unknown.log" not in self.manager.global_template_handlers

    def test_clear_resources_removes_all_resources_and_handlers(self):
        # Arrange - add multiple resources
        resource2 = Resource(uri="file:///test2.txt", name="Test File 2")
        mock_handler2 = AsyncMock()

        self.manager.add_resource(self.test_resource, self.mock_handler)
        self.manager.add_resource(resource2, mock_handler2)

        # Verify they were added
        assert len(self.manager.get_resources()) == 2
        assert len(self.manager.global_handlers) == 2

        # Act
        self.manager.clear_resources()

        # Assert
        # Verify all resources are removed
        resources = self.manager.get_resources()
        assert len(resources) == 0

        # Verify all handlers are removed internally
        assert len(self.manager.global_handlers) == 0

    def test_clear_templates_removes_all_templates_and_handlers(self):
        # Arrange - add multiple templates
        template2 = ResourceTemplate(
            uri_template="file:///data/{id}.json", name="Data Template"
        )
        mock_handler2 = AsyncMock()

        self.manager.add_template(self.test_template, self.mock_handler)
        self.manager.add_template(template2, mock_handler2)

        # Verify they were added
        assert len(self.manager.get_templates()) == 2
        assert len(self.manager.global_template_handlers) == 2

        # Act
        self.manager.clear_templates()

        # Assert
        # Verify all templates are removed
        templates = self.manager.get_templates()
        assert len(templates) == 0

        # Verify all handlers are removed internally
        assert len(self.manager.global_template_handlers) == 0


class TestClientResourceManagement:
    def setup_method(self):
        # Arrange - setup already done in setup_method
        self.manager = ResourceManager()
        self.test_resource = Resource(uri="file:///test.txt", name="Test File")
        self.test_template = ResourceTemplate(
            uri_template="file:///logs/{date}.log", name="Log Template"
        )
        self.mock_handler = AsyncMock()
        self.client_id = "client-123"

    def test_add_client_resource_stores_resource_and_handler(self):
        # Arrange - setup already done in setup_method

        # Act
        self.manager.add_client_resource(
            self.client_id, self.test_resource, self.mock_handler
        )

        # Assert
        # Verify client resource is stored
        assert self.client_id in self.manager.client_resources
        assert "file:///test.txt" in self.manager.client_resources[self.client_id]
        assert (
            self.manager.client_resources[self.client_id]["file:///test.txt"]
            == self.test_resource
        )

        # Verify handler is stored internally
        assert self.client_id in self.manager.client_handlers
        assert "file:///test.txt" in self.manager.client_handlers[self.client_id]
        assert (
            self.manager.client_handlers[self.client_id]["file:///test.txt"]
            == self.mock_handler
        )

    def test_add_client_template_stores_template_and_handler(self):
        # Arrange - setup already done in setup_method

        # Act
        self.manager.add_client_template(
            self.client_id, self.test_template, self.mock_handler
        )

        # Assert
        # Verify client template is stored
        assert self.client_id in self.manager.client_templates
        assert (
            "file:///logs/{date}.log" in self.manager.client_templates[self.client_id]
        )
        assert (
            self.manager.client_templates[self.client_id]["file:///logs/{date}.log"]
            == self.test_template
        )

        # Verify handler is stored internally
        assert self.client_id in self.manager.client_template_handlers
        assert (
            "file:///logs/{date}.log"
            in self.manager.client_template_handlers[self.client_id]
        )
        assert (
            self.manager.client_template_handlers[self.client_id][
                "file:///logs/{date}.log"
            ]
            == self.mock_handler
        )

    def test_get_client_resources_returns_global_resources(self):
        # Arrange - add only global resource
        self.manager.add_resource(self.test_resource, self.mock_handler)

        # Act
        client_resources = self.manager.get_client_resources(self.client_id)

        # Assert
        assert "file:///test.txt" in client_resources
        assert client_resources["file:///test.txt"] == self.test_resource
        assert len(client_resources) == 1

    def test_get_client_resources_returns_global_plus_client_specific(self):
        # Arrange - add global and client-specific resources
        global_resource = Resource(uri="file:///global.txt", name="Global File")
        client_resource = Resource(uri="file:///client.txt", name="Client File")

        self.manager.add_resource(global_resource, self.mock_handler)
        self.manager.add_client_resource(
            self.client_id, client_resource, self.mock_handler
        )

        # Act
        client_resources = self.manager.get_client_resources(self.client_id)

        # Assert
        assert len(client_resources) == 2
        assert "file:///global.txt" in client_resources
        assert "file:///client.txt" in client_resources
        assert client_resources["file:///global.txt"] == global_resource
        assert client_resources["file:///client.txt"] == client_resource

    def test_get_client_resources_client_specific_overrides_global(self):
        # Arrange - add global resource, then client-specific with same URI
        global_resource = Resource(uri="file:///test.txt", name="Global File")
        client_resource = Resource(uri="file:///test.txt", name="Client Override File")

        self.manager.add_resource(global_resource, self.mock_handler)
        self.manager.add_client_resource(
            self.client_id, client_resource, self.mock_handler
        )

        # Act
        client_resources = self.manager.get_client_resources(self.client_id)

        # Assert
        assert len(client_resources) == 1
        assert client_resources["file:///test.txt"] == client_resource
        assert client_resources["file:///test.txt"].name == "Client Override File"

    def test_get_client_templates_returns_global_templates(self):
        # Arrange - add only global template
        self.manager.add_template(self.test_template, self.mock_handler)

        # Act
        client_templates = self.manager.get_client_templates(self.client_id)

        # Assert
        assert "file:///logs/{date}.log" in client_templates
        assert client_templates["file:///logs/{date}.log"] == self.test_template
        assert len(client_templates) == 1

    def test_get_client_templates_returns_global_plus_client_specific(self):
        # Arrange - add global and client-specific templates
        global_template = ResourceTemplate(
            uri_template="file:///global/{id}.txt", name="Global Template"
        )
        client_template = ResourceTemplate(
            uri_template="file:///client/{id}.txt", name="Client Template"
        )

        self.manager.add_template(global_template, self.mock_handler)
        self.manager.add_client_template(
            self.client_id, client_template, self.mock_handler
        )

        # Act
        client_templates = self.manager.get_client_templates(self.client_id)

        # Assert
        assert len(client_templates) == 2
        assert "file:///global/{id}.txt" in client_templates
        assert "file:///client/{id}.txt" in client_templates
        assert client_templates["file:///global/{id}.txt"] == global_template
        assert client_templates["file:///client/{id}.txt"] == client_template

    def test_get_client_templates_client_specific_overrides_global(self):
        # Arrange - add global template, then client-specific with same pattern
        global_template = ResourceTemplate(
            uri_template="file:///logs/{date}.log", name="Global Log Template"
        )
        client_template = ResourceTemplate(
            uri_template="file:///logs/{date}.log", name="Client Log Template"
        )

        self.manager.add_template(global_template, self.mock_handler)
        self.manager.add_client_template(
            self.client_id, client_template, self.mock_handler
        )

        # Act
        client_templates = self.manager.get_client_templates(self.client_id)

        # Assert
        assert len(client_templates) == 1
        assert client_templates["file:///logs/{date}.log"] == client_template
        assert client_templates["file:///logs/{date}.log"].name == "Client Log Template"

    def test_remove_client_resource_removes_resource_and_handler(self):
        # Arrange - add client resource first
        self.manager.add_client_resource(
            self.client_id, self.test_resource, self.mock_handler
        )
        assert "file:///test.txt" in self.manager.client_resources[self.client_id]
        assert "file:///test.txt" in self.manager.client_handlers[self.client_id]

        # Act
        self.manager.remove_client_resource(self.client_id, "file:///test.txt")

        # Assert
        # Verify resource is removed
        assert "file:///test.txt" not in self.manager.client_resources[self.client_id]

        # Verify handler is removed internally
        assert "file:///test.txt" not in self.manager.client_handlers[self.client_id]

    def test_remove_client_resource_silently_succeeds_for_unknown_client(self):
        # Act - remove from non-existent client
        self.manager.remove_client_resource("unknown-client", "file:///test.txt")

        # Assert - no error thrown, no state changed
        assert "unknown-client" not in self.manager.client_resources

    def test_remove_client_template_removes_template_and_handler(self):
        # Arrange - add client template first
        self.manager.add_client_template(
            self.client_id, self.test_template, self.mock_handler
        )
        assert (
            "file:///logs/{date}.log" in self.manager.client_templates[self.client_id]
        )
        assert (
            "file:///logs/{date}.log"
            in self.manager.client_template_handlers[self.client_id]
        )

        # Act
        self.manager.remove_client_template(self.client_id, "file:///logs/{date}.log")

        # Assert
        # Verify template is removed
        assert (
            "file:///logs/{date}.log"
            not in self.manager.client_templates[self.client_id]
        )

        # Verify handler is removed internally
        assert (
            "file:///logs/{date}.log"
            not in self.manager.client_template_handlers[self.client_id]
        )

    def test_remove_client_template_silently_succeeds_for_unknown_client(self):
        # Act - remove from non-existent client
        self.manager.remove_client_template("unknown-client", "file:///logs/{date}.log")

        # Assert - no error thrown, no state changed
        assert "unknown-client" not in self.manager.client_templates

    def test_cleanup_client_removes_all_client_data(self):
        # Arrange - add resources, templates, and subscriptions for client
        self.manager.add_client_resource(
            self.client_id, self.test_resource, self.mock_handler
        )
        self.manager.add_client_template(
            self.client_id, self.test_template, self.mock_handler
        )

        # Add subscription manually to test cleanup
        self.manager._client_subscriptions[self.client_id] = {"file:///test.txt"}

        # Verify everything was added
        assert self.client_id in self.manager.client_resources
        assert self.client_id in self.manager.client_handlers
        assert self.client_id in self.manager.client_templates
        assert self.client_id in self.manager.client_template_handlers
        assert self.client_id in self.manager._client_subscriptions

        # Act
        self.manager.cleanup_client(self.client_id)

        # Assert - all client data is removed
        assert self.client_id not in self.manager.client_resources
        assert self.client_id not in self.manager.client_handlers
        assert self.client_id not in self.manager.client_templates
        assert self.client_id not in self.manager.client_template_handlers
        assert self.client_id not in self.manager._client_subscriptions

    def test_cleanup_client_silently_succeeds_for_unknown_client(self):
        # Act - cleanup non-existent client
        self.manager.cleanup_client("unknown-client")

        # Assert - no error thrown, no state changed
        assert "unknown-client" not in self.manager.client_resources
        assert "unknown-client" not in self.manager.client_handlers
        assert "unknown-client" not in self.manager.client_templates
        assert "unknown-client" not in self.manager.client_template_handlers
        assert "unknown-client" not in self.manager._client_subscriptions
