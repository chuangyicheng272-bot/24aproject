$body = @{
    device_id = "W-001"
    x = 12.5
    y = 8.2
    z = 1.4
    helmet = $true
    vest = $true
    battery = 88
    timestamp = (Get-Date).ToString("o")
} | ConvertTo-Json

$result = Invoke-RestMethod `
    -Uri "http://127.0.0.1:5000/api/iot/uwb" `
    -Method POST `
    -ContentType "application/json" `
    -Body $body

$result | ConvertTo-Json -Depth 10
