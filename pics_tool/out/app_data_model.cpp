    /* Create a Matter node with the Root Node device type on endpoint 0. */
    node::config_t node_config;
    node_t *node = node::create(&node_config, app_attribute_update_cb, app_identification_cb);
    ABORT_APP_ON_FAILURE(node != nullptr, ESP_LOGE(TAG, "Failed to create Matter node"));

    /* Endpoint 1: Extended Color Light (default config; set attribute defaults as needed). */
    extended_color_light::config_t extended_color_light_config_1;
    endpoint_t *endpoint_1 = extended_color_light::create(node, &extended_color_light_config_1, ENDPOINT_FLAG_NONE, priv_data);
    ABORT_APP_ON_FAILURE(endpoint_1 != nullptr, ESP_LOGE(TAG, "Failed to create Extended Color Light endpoint"));

    uint16_t endpoint_id = endpoint::get_id(endpoint_1);
