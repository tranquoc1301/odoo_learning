from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ShopifySyncWizard(models.TransientModel):
    _name = "shopify.sync.wizard"
    _description = "Shopify Manual Sync Wizard"

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("done", "Done"),
        ],
        string="State",
        default="draft",
        readonly=True,
    )

    config_id = fields.Many2one(
        "shopify.config",
        string="Shopify Store",
        required=True,
        domain="[('active', '=', True)]",
    )
    sync_type = fields.Selection(
        [
            ("products", "Products"),
            ("orders", "Orders"),
            ("inventory", "Inventory"),
            ("all", "All"),
        ],
        string="Sync Type",
        required=True,
        default="all",
    )
    date_from = fields.Datetime(
        string="Date From",
        help="Only applicable for order sync. Leave empty to use last sync date.",
    )
    date_to = fields.Datetime(
        string="Date To",
        help="Only applicable for order sync. Leave empty to sync until now.",
    )

    total_created = fields.Integer(string="Created", readonly=True)
    total_updated = fields.Integer(string="Updated", readonly=True)
    total_errors = fields.Integer(string="Errors", readonly=True)
    summary_html = fields.Html(string="Summary", readonly=True, sanitize=False)

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise UserError(_("Date From must be earlier than Date To."))

    def _get_sync_label(self, key):
        labels = {
            "products": _("Products"),
            "orders": _("Orders"),
            "inventory": _("Inventory"),
        }
        return labels.get(key, key.capitalize())

    def _build_summary(self, result_map):
        """Build an HTML table summary and return write-ready vals dict."""
        total_created = total_updated = total_errors = 0
        body_rows = ""

        for key in ("products", "inventory", "orders"):
            res = result_map.get(key)
            if not isinstance(res, dict):
                continue

            c = int(res.get("created", 0) or 0)
            u = int(res.get("updated", 0) or 0)
            e = int(res.get("errors", 0) or 0)
            total_created += c
            total_updated += u
            total_errors += e

            row_cls = "table-danger" if e else ""
            errors_cls = "text-danger fw-bold" if e else "text-muted"

            body_rows += (
                f"<tr class='{row_cls}'>"
                f"  <td class='ps-3'><strong>{self._get_sync_label(key)}</strong></td>"
                f"  <td class='text-center text-success fw-semibold'>{c}</td>"
                f"  <td class='text-center text-warning fw-semibold'>{u}</td>"
                f"  <td class='text-center {errors_cls}'>{e}</td>"
                f"</tr>"
            )

        if not body_rows:
            body_rows = (
                f"<tr><td colspan='4' class='text-center text-muted fst-italic py-3'>"
                f"{_('No data returned.')}</td></tr>"
            )

        footer_err_cls = "text-danger" if total_errors else "text-success"

        # Dùng FontAwesome 4.x — có sẵn trong Odoo 19
        if total_errors:
            status_badge = (
                f"<span class='badge text-bg-danger ms-2'>"
                f"<i class='fa fa-exclamation-triangle me-1'/>{_('Errors found')}"
                f"</span>"
            )
        else:
            status_badge = (
                f"<span class='badge text-bg-success ms-2'>"
                f"<i class='fa fa-check me-1'/>{_('All good')}"
                f"</span>"
            )

        summary = f"""
    <div class="o_field_html">
      <table class="table table-sm table-bordered table-hover mb-0">
        <thead class="table-secondary text-center">
          <tr>
            <th class="text-start ps-3" style="width:36%">{_('Sync Type')}</th>
            <th style="width:21%">
              <i class="fa fa-plus-circle text-success me-1"/>{_('Created')}
            </th>
            <th style="width:21%">
              <i class="fa fa-pencil text-warning me-1"/>{_('Updated')}
            </th>
            <th style="width:22%">
              <i class="fa fa-times-circle text-danger me-1"/>{_('Errors')}
            </th>
          </tr>
        </thead>
        <tbody>
          {body_rows}
        </tbody>
        <tfoot class="table-light text-center fw-bold">
          <tr>
            <td class="text-start ps-3">
              {_('Total')} {status_badge}
            </td>
            <td class="text-success">{total_created}</td>
            <td class="text-warning">{total_updated}</td>
            <td class="{footer_err_cls}">{total_errors}</td>
          </tr>
        </tfoot>
      </table>
    </div>"""

        return {
            "total_created": total_created,
            "total_updated": total_updated,
            "total_errors": total_errors,
            "summary_html": summary,
        }

    def _run_selected_sync(self):
        self.ensure_one()
        config = self.config_id

        if self.sync_type == "products":
            return {
                "products": config.sync_products(),
            }

        if self.sync_type == "orders":
            return {
                "orders": config.sync_orders(
                    date_from=self.date_from,
                    date_to=self.date_to,
                ),
            }

        if self.sync_type == "inventory":
            return {
                "inventory": config.sync_inventory(),
            }

        return {
            "products": config.sync_products(),
            "inventory": config.sync_inventory(),
            "orders": config.sync_orders(
                date_from=self.date_from,
                date_to=self.date_to,
            ),
        }

    def action_sync(self):
        self.ensure_one()

        result_map = self._run_selected_sync()
        summary_vals = self._build_summary(result_map)

        self.write({
            "state": "done",
            **summary_vals,
        })

        return {
            "type": "ir.actions.act_window",
            "name": _("Sync Summary"),
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

    def action_reset(self):
        self.ensure_one()
        self.write({
            "state": "draft",
            "total_created": 0,
            "total_updated": 0,
            "total_errors": 0,
            "summary_html": False,
        })

        return {
            "type": "ir.actions.act_window",
            "name": _("Manual Sync"),
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

    def action_close(self):
        return {"type": "ir.actions.act_window_close"}
