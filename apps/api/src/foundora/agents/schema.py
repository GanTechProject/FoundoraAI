from __future__ import annotations


class AgentSchemaError(ValueError):
    pass


def validate_schema(value: object, schema: dict[str, object], path: str = "$") -> None:
    """Validate the intentionally small JSON Schema subset used by agent contracts."""
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise AgentSchemaError(f"{path} must be an object")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise AgentSchemaError(f"{path} schema properties are invalid")
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise AgentSchemaError(f"{path} schema required fields are invalid")
        missing = [item for item in required if item not in value]
        if missing:
            raise AgentSchemaError(f"{path} is missing required fields: {', '.join(missing)}")
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value).difference(properties))
            if extras:
                raise AgentSchemaError(f"{path} has unsupported fields: {', '.join(extras)}")
        for key, item in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                validate_schema(item, child_schema, f"{path}.{key}")
        return
    if expected == "array":
        if not isinstance(value, list):
            raise AgentSchemaError(f"{path} must be an array")
        maximum = schema.get("maxItems")
        if isinstance(maximum, int) and len(value) > maximum:
            raise AgentSchemaError(f"{path} exceeds its item limit")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate_schema(item, item_schema, f"{path}[{index}]")
        return
    if expected == "string":
        if not isinstance(value, str):
            raise AgentSchemaError(f"{path} must be a string")
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            raise AgentSchemaError(f"{path} is shorter than allowed")
        if isinstance(maximum, int) and len(value) > maximum:
            raise AgentSchemaError(f"{path} is longer than allowed")
        return
    if expected == "boolean":
        if not isinstance(value, bool):
            raise AgentSchemaError(f"{path} must be a boolean")
        return
    if expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise AgentSchemaError(f"{path} must be an integer")
        return
    if expected is not None:
        raise AgentSchemaError(f"{path} uses an unsupported schema type")
