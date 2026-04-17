from odoo import _

_BLUE = "#0d6efd"
_ORANGE = "#fd7e14"
_GREEN = "#198754"
_RED = "#dc3545"
_GREY = "#6c757d"
_BG = "#f8f9fa"
_BORDER = "rgba(0,0,0,.08)"

_CARD = (
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
    "background:#ffffff;"
    "border-radius:10px;"
    "box-shadow:0 0 0 1px rgba(0,0,0,.10);"
    "overflow:hidden;"
    "max-width:560px;"
    "color:#212529"
)

_TABLE = "width:100%;border-collapse:collapse"

_TH = (
    f"font-size:11px;font-weight:600;color:{_GREY};"
    "text-transform:uppercase;letter-spacing:.5px;"
    f"padding:9px 16px;text-align:left;"
    f"background:{_BG};"
    f"border-bottom:1px solid {_BORDER}"
)
_TH_CENTER = _TH + ";text-align:center"

_TD = (
    "padding:11px 16px;"
    "border-bottom:1px solid rgba(0,0,0,.05);"
    "font-size:13px;color:#212529;vertical-align:middle"
)
_TD_CENTER = _TD + ";text-align:center"

_TF = (
    f"padding:9px 16px;"
    f"background:{_BG};"
    f"border-top:2px solid {_BORDER};"
    "font-size:12px;font-weight:600;color:#212529;vertical-align:middle"
)
_TF_CENTER = _TF + ";text-align:center"

_LABEL_WRAP = "display:inline-flex;align-items:center;gap:9px"

_ROW_ICON_WRAP = (
    "width:26px;height:26px;border-radius:6px;"
    "display:inline-flex;align-items:center;justify-content:center;flex-shrink:0"
)

_FOOTER = (
    "display:flex;align-items:center;justify-content:space-between;"
    "padding:10px 16px;"
    f"background:{_BG};"
    f"border-top:1px solid {_BORDER}"
)

_TOTALS = "display:flex;gap:16px"
_TOTAL_ITEM = f"display:inline-flex;align-items:center;gap:5px;font-size:12px;color:{_GREY}"

_ROW_META = {
    "products": {
        "label_key": "Products",
        "icon_bg": "#dbeafe",
        "fa_cls": "fa-tag",
        "fa_color": _BLUE,
    },
    "inventory": {
        "label_key": "Inventory",
        "icon_bg": "#fff3cd",
        "fa_cls": "fa-cubes",
        "fa_color": _ORANGE,
    },
    "orders": {
        "label_key": "Orders",
        "icon_bg": "#d1e7dd",
        "fa_cls": "fa-shopping-cart",
        "fa_color": _GREEN,
    },
}


def _fa(cls, color, size="13px"):
    return (
        f'<i class="fa {cls}" aria-hidden="true" '
        f'style="font-size:{size};color:{color};line-height:1"></i>'
    )


def _badge(value, style="muted"):
    palettes = {
        "success": (f"background:#d1e7dd;color:{_GREEN}", value),
        "warning": (f"background:#fff3cd;color:#856404", value),
        "danger": (f"background:#f8d7da;color:{_RED}", value),
        "muted": (f"background:#e9ecef;color:{_GREY}", value),
    }
    css, val = palettes.get(style, palettes["muted"])
    return (
        f'<span style="display:inline-flex;align-items:center;justify-content:center;'
        f'font-size:12px;font-weight:600;padding:2px 10px;border-radius:20px;'
        f'min-width:34px;{css}">{val}</span>'
    )


def _dash():
    return '<span style="font-size:16px;color:#dee2e6;font-weight:300;line-height:1">—</span>'


def _status_pill(total_created, total_updated, total_errors):
    if total_errors:
        dot, css, text = _RED, f"background:#f8d7da;color:{_RED}", _("Completed with errors")
    elif total_created or total_updated:
        dot, css, text = _GREEN, f"background:#d1e7dd;color:{_GREEN}", _("Completed successfully")
    else:
        dot, css, text = _GREY, f"background:#e9ecef;color:{_GREY}", _("No changes")

    return (
        f'<span style="display:inline-flex;align-items:center;gap:5px;'
        f'font-size:12px;font-weight:500;padding:4px 11px;border-radius:20px;{css}">'
        f'<span style="width:6px;height:6px;border-radius:50%;'
        f'background:{dot};flex-shrink:0"></span>{text}</span>'
    )


def build_sync_summary_html(result_map):
    total_created = total_updated = total_errors = 0
    rows_html = ""
    is_even = True

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

        meta = _ROW_META[key]
        label = _(meta["label_key"])
        icon_bg = meta["icon_bg"]
        fa_icon = _fa(meta["fa_cls"], meta["fa_color"])
        row_bg = "" if is_even else "background:#fafafa;"
        is_even = not is_even

        rows_html += (
            f'<tr style="{row_bg}">'
            f'<td style="{_TD}">'
            f'<span style="{_LABEL_WRAP}">'
            f'<span style="{_ROW_ICON_WRAP};background:{icon_bg}">{fa_icon}</span>'
            f'<span style="font-weight:500">{label}</span>'
            f'</span>'
            f'</td>'
            f'<td style="{_TD_CENTER}">{_badge(c, "success") if c else _dash()}</td>'
            f'<td style="{_TD_CENTER}">{_badge(u, "warning") if u else _dash()}</td>'
            f'<td style="{_TD_CENTER}">{_badge(e, "danger") if e else _dash()}</td>'
            f'</tr>'
        )

    if not rows_html:
        rows_html = (
            f'<tr><td colspan="4" style="{_TD};text-align:center;'
            f'padding:24px;color:{_GREY}">{_("No data returned.")}</td></tr>'
        )

    tfoot_err_badge = _badge(total_errors, "danger") if total_errors else _badge(total_errors, "muted")

    status_pill = _status_pill(total_created, total_updated, total_errors)
    err_color = _RED if total_errors else "#212529"
    err_html = f'<b style="color:{err_color}">{total_errors}</b>'

    icon_check = _fa("fa-check-circle", _GREEN)
    icon_pencil = _fa("fa-pencil", _ORANGE)
    icon_excl = _fa("fa-exclamation-circle", _RED if total_errors else _GREY)

    return (
        f'<div style="{_CARD}">'

        f'<table style="{_TABLE}">'

        f'<thead>'
        f'<tr>'
        f'<th style="{_TH};width:40%">{_("Sync type")}</th>'
        f'<th style="{_TH_CENTER};width:20%">'
        f'{_fa("fa-plus-circle", _GREEN, "11px")}&nbsp;{_("Created")}'
        f'</th>'
        f'<th style="{_TH_CENTER};width:20%">'
        f'{_fa("fa-pencil", _ORANGE, "11px")}&nbsp;{_("Updated")}'
        f'</th>'
        f'<th style="{_TH_CENTER};width:20%">'
        f'{_fa("fa-exclamation-circle", _RED, "11px")}&nbsp;{_("Errors")}'
        f'</th>'
        f'</tr>'
        f'</thead>'

        f'<tbody>{rows_html}</tbody>'

        f'<tfoot>'
        f'<tr>'
        f'<td style="{_TF}">'
        f'<span style="color:{_GREY};font-size:11px;text-transform:uppercase;letter-spacing:.5px">'
        f'{_fa("fa-bar-chart", _GREY, "11px")}&nbsp;{_("Total")}'
        f'</span>'
        f'</td>'
        f'<td style="{_TF_CENTER}">{_badge(total_created, "success") if total_created else _badge(0, "muted")}</td>'
        f'<td style="{_TF_CENTER}">{_badge(total_updated, "warning") if total_updated else _badge(0, "muted")}</td>'
        f'<td style="{_TF_CENTER}">{tfoot_err_badge}</td>'
        f'</tr>'
        f'</tfoot>'

        f'</table>'

        f'<div style="{_FOOTER}">'
        f'<div style="{_TOTALS}">'
        f'<span style="{_TOTAL_ITEM}">{icon_check}&nbsp;<b style="color:#212529">{total_created}</b>&nbsp;{_("created")}</span>'
        f'<span style="{_TOTAL_ITEM}">{icon_pencil}&nbsp;<b style="color:#212529">{total_updated}</b>&nbsp;{_("updated")}</span>'
        f'<span style="{_TOTAL_ITEM}">{icon_excl}&nbsp;{err_html}&nbsp;{_("errors")}</span>'
        f'</div>'
        f'{status_pill}'
        f'</div>'

        f'</div>'
    )
