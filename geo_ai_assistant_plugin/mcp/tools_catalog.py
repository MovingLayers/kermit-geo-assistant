QGIS_TOOLS_CATALOG: list[dict] = [
    {
        "name": "get_layers",
        "description": "Retrieve all layers in the current QGIS project",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "add_vector_layer",
        "description": "Add a vector layer to the project",
        "inputSchema": {
            "type": "object",
            "required": ["path", "name"],
            "properties": {
                "path":     {"type": "string", "description": "File path to the vector data source"},
                "name":     {"type": "string", "description": "Display name for the layer"},
                "provider": {"type": "string", "description": "Data provider key (default: ogr)"},
            },
        },
    },
    {
        "name": "execute_code",
        "description": "Execute arbitrary PyQGIS code",
        "inputSchema": {
            "type": "object",
            "required": ["code"],
            "properties": {
                "code": {"type": "string", "description": "PyQGIS source code to run"},
            },
        },
    },
]