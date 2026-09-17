"""Print recent LINE delivery results without exposing credentials."""

import json
import re
import sqlite3


connection = sqlite3.connect("safeguard.db")
connection.row_factory = sqlite3.Row
deliveries = [
    dict(row)
    for row in connection.execute(
        """
        SELECT id,alert_id,recipient,status,attempts,http_status,failure_reason,updated_at
        FROM line_alert_deliveries
        ORDER BY id DESC LIMIT 10
        """
    )
]
connection.close()
for delivery in deliveries:
    recipient = delivery.pop("recipient", "")
    delivery["recipient_length"] = len(recipient)
    delivery["recipient_format_valid"] = bool(
        re.fullmatch(r"U[0-9a-f]{32}", recipient)
    )
print(json.dumps(deliveries, ensure_ascii=True, indent=2))
