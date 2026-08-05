#pragma once

#include <esp_matter.h>

/** Create the Matter node and the "Extended Color Light" endpoint.
 *
 * @param[in]  attribute_update_cb  Attribute-update callback passed to node::create.
 * @param[in]  identification_cb    Identify callback passed to node::create.
 * @param[in]  priv_data            Private data handed to the application endpoint.
 * @param[out] app_endpoint_id      Set to the created application endpoint id (optional).
 *
 * @return the created node, or nullptr on failure.
 */
esp_matter::node_t *create_data_model(esp_matter::attribute::callback_t attribute_update_cb,
                                      esp_matter::identification::callback_t identification_cb,
                                      void *priv_data,
                                      uint16_t *app_endpoint_id);
