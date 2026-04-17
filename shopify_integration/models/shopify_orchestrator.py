import logging

from odoo import _, models

_logger = logging.getLogger(__name__)


class ShopifyOrchestrator(models.Model):
    """Handles sync workflow and scheduling."""

    _name = "shopify.orchestrator"
    _description = "Shopify Sync Orchestrator"

    def sync_all(self, config):
        """Run products → orders → inventory in sequence."""
        config.ensure_one()
        result = {}
        total_errors = 0

        for key, method in (
            ("products", config.sync_products),
            ("orders", config.sync_orders),
            ("inventory", config.sync_inventory),
        ):
            try:
                result[key] = method()
            except Exception:
                _logger.exception(
                    "sync_all: %s failed for config %s", key, config.display_name
                )
                result[key] = {"created": 0, "updated": 0, "errors": 1}

            total_errors += result[key].get("errors", 0)

        self.env["sync.log"].create_from_config(
            config,
            sync_type="all",
            status="failed" if total_errors else "success",
            message=_("Sync all completed — errors: %s") % total_errors,
        )

        return result

    def _run_cron_sync(self, config, method_name):
        try:
            getattr(config, method_name)()
        except Exception:
            _logger.exception(
                "Cron %s failed for config %s", method_name, config.display_name
            )

    def _run_cron_for_all_active_configs(self, method_name):
        config_env = self.env["shopify.config"]
        for config in config_env.search([("active", "=", True)]):
            self._run_cron_sync(config, method_name)
        return True

    def cron_sync_products(self):
        return self._run_cron_for_all_active_configs("sync_products")

    def cron_sync_orders(self):
        return self._run_cron_for_all_active_configs("sync_orders")

    def cron_sync_inventory(self):
        return self._run_cron_for_all_active_configs("sync_inventory")
