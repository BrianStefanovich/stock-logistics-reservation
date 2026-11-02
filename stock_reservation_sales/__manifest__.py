# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

{
    "name": "Stock - Sales Reservations",
    "summary": "Let salespeople reserve stock without a sales order, "
    "with automatic expiration",
    "version": "20.0.1.0.0",
    "category": "Reservation",
    "license": "AGPL-3",
    "author": "Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/stock-logistics-reservation",
    "depends": ["stock", "stock_quant_manual_assign"],
    "data": [
        "security/security.xml",
        "security/ir.access.csv",
        "data/ir_sequence_data.xml",
        "data/ir_cron_data.xml",
        "views/stock_sales_reservation_views.xml",
    ],
    "installable": True,
}
