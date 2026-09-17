(() => {
  const STORAGE_KEY = 'safeguard-language';
  const DEFAULT_LANGUAGE = 'zh-Hant';
  const SUPPORTED_LANGUAGES = new Set(['zh-Hant', 'en']);

  const ENGLISH = Object.freeze({
    '語言': 'Language',
    '登出': 'Log out',
    '登入': 'Log in',
    '登入｜SafeGuard': 'Log in | SafeGuard',
    '登入系統': 'System Login',
    '請輸入管理員提供的帳號與密碼。': 'Enter the account and password provided by the administrator.',
    '帳號 (Account)': 'Account',
    '密碼 (Password)': 'Password',
    '輸入使用者帳號': 'Enter account',
    '輸入使用者密碼': 'Enter password',
    '忘記密碼？': 'Forgot password?',
    '登入　→': 'Log in →',
    '示範帳號：admin　密碼：admin123': 'Demo account: admin   Password: admin123',
    '忘記密碼': 'Forgot Password',
    '輸入帳號與管理員設定的電子郵件，系統會寄送 10 分鐘有效的重設連結。': 'Enter your account and administrator-configured email. A reset link valid for 10 minutes will be sent.',
    '為保護帳戶安全，不論資料是否相符，畫面都會顯示相同結果。': 'For account security, the same result is shown whether or not the information matches.',
    '寄送重設連結': 'Send Reset Link',
    '電子郵件': 'Email',
    '取消': 'Cancel',
    '儲存': 'Save',
    '搜尋': 'Search',
    '編輯': 'Edit',
    '刪除': 'Delete',
    '移除': 'Remove',
    '操作': 'Actions',
    '狀態': 'Status',
    '正常': 'Online',
    '離線': 'Offline',
    '異常': 'Abnormal',
    '連線中': 'Connected',
    '已連線': 'Connected',
    '未連線': 'Disconnected',
    '未啟用': 'Disabled',
    '啟用': 'Enabled',
    '停用': 'Disabled',
    '未設定': 'Not configured',
    '尚未設定': 'Not configured',
    '尚未新增': 'Not added yet',
    '等待資料': 'Waiting for data',
    '等待連線': 'Waiting for connection',
    '尚未收到資料': 'No data received',
    '尚未匯入': 'Not imported yet',
    '尚未同步': 'Not synchronized',
    '尚無紀錄': 'No records yet',
    '載入中...': 'Loading...',
    '載入中…': 'Loading…',
    '讀取中': 'Loading',
    '全部': 'All',
    '成功': 'Success',
    '失敗': 'Failed',
    '處理中': 'Processing',
    '已完成': 'Completed',
    '未處理': 'Unresolved',
    '已處理': 'Resolved',
    '低風險': 'Low risk',
    '注意': 'Attention',
    '中高風險': 'Medium-high risk',
    '緊急': 'Emergency',
    '嚴重': 'Serious',
    '一般使用者': 'Standard user',
    '管理員': 'Administrator',
    '系統管理員': 'System Administrator',
    '未綁定': 'Unassigned',
    '👤 未綁定': '👤 Unassigned',
    '剛剛': 'Just now',
    '返回': 'Back',
    '返回系統總覽': 'Back to Dashboard',
    '← 返回儀表板': '← Back to Dashboard',
    '← 返回登入頁': '← Back to Login',
    '首頁　/　系統總覽　/　帳戶管理': 'Home / Dashboard / Account Management',
    '首頁　/　系統總覽　/　帳戶管理　/　Email 郵寄服務': 'Home / Dashboard / Account Management / Email Service',

    '系統總覽 (Dashboard)': 'System Dashboard',
    '👥 管理帳戶': '👥 Manage Accounts',
    '🗄 SQLite 資料庫': '🗄 SQLite Database',
    '🚨 即時危險警報': '🚨 Real-time Safety Alerts',
    '重新整理 ↻': 'Refresh ↻',
    '↻ 重新整理': '↻ Refresh',
    '設備人員': 'Personnel Devices',
    'PPE 穿戴率': 'PPE Compliance',
    '點名合計': 'Attendance Total',
    '各系統連線狀態：': 'Connected system status:',
    '👥 人員管理': '👥 Personnel Management',
    '人員管理': 'Personnel Management',
    '監控設備': 'Monitoring Devices',
    '監控中攝影機：': 'Active cameras:',
    '支': 'cameras',
    '筆': 'records',
    '人': 'people',
    '位人員': 'people',
    '攝影機狀態：': 'Camera status:',
    '查看詳細內容 →': 'View details →',
    '人員清單': 'Personnel List',
    '目前尚無人員資料': 'No personnel data available',
    '前往人員管理 →': 'Go to Personnel Management →',
    '設定區域': 'Area Settings',
    '建立區域並管理各區域的 UWB 基站': 'Create areas and manage their UWB base stations',
    '前往設定區域 →': 'Go to Area Settings →',
    '🔗 所有連線系統 (Connected Systems)': '🔗 Connected Systems',
    'UWB 電子圍籬系統': 'UWB Electronic Fence System',
    '狀態：': 'Status:',
    '系統連線正常': 'System connected',
    '開啟 UWB 區域監看 →': 'Open UWB Area Monitoring →',
    'Yolo (影像辨識系統)': 'YOLO (Vision Recognition System)',
    '攝影機辨識中': 'Camera recognition active',
    '開啟 YOLO 串流監看 →': 'Open YOLO Stream Monitoring →',
    'LINE Bot / 通知系統': 'LINE Bot / Notification System',
    '前往設定頁面 →': 'Go to Settings →',
    'MQTT / API 服務': 'MQTT / API Services',
    '前往 API 設定 →': 'Go to API Settings →',

    '帳戶管理｜SafeGuard': 'Account Management | SafeGuard',
    '帳戶管理功能': 'Account management features',
    '所有帳戶': 'All Accounts',
    'Email 郵寄服務': 'Email Service',
    '所有帳戶管理': 'Account Management',
    '新增、編輯、停用或刪除系統帳戶；管理員可在「編輯」中輸入新密碼進行人工重設。': 'Add, edit, disable, or delete system accounts. Administrators can manually reset a password while editing an account.',
    '＋ 新增帳戶': '+ Add Account',
    '帳號、姓名、電話或電子郵件': 'Account, name, phone, or email',
    '⇩ 匯出 CSV': '⇩ Export CSV',
    '帳號': 'Account',
    '姓名': 'Name',
    '電話': 'Phone',
    '角色': 'Role',
    '建立日期': 'Created Date',
    '新增帳戶': 'Add Account',
    '編輯帳戶': 'Edit Account',
    '用於寄送忘記密碼重設連結與帳戶安全通知。': 'Used for password reset links and account security notifications.',
    '密碼': 'Password',
    '（編輯時輸入新密碼即可人工重設；留白則不變更）': '(Enter a new password to reset it manually; leave blank to keep the current password.)',
    '例如 0912345678': 'Example: 0912345678',
    '請輸入有效的電子郵件地址': 'Enter a valid email address',
    '帳戶資料已儲存': 'Account saved',
    '帳號狀態已更新': 'Account status updated',
    '使用者已刪除': 'User deleted',
    '確定要刪除此使用者？': 'Are you sure you want to delete this user?',

    'Email 郵寄服務｜SafeGuard': 'Email Service | SafeGuard',
    '管理郵件連線與系統通知紀錄': 'Manage email connectivity and system notification records',
    '寄件者信箱': 'Sender Email',
    'SMTP 伺服器': 'SMTP Server',
    '加密方式': 'Encryption',
    '最後檢查': 'Last Check',
    '↻ 重新檢查': '↻ Check Again',
    '✉ 寄送測試信': '✉ Send Test Email',
    '最近寄送紀錄': 'Recent Delivery History',
    '查看忘記密碼與系統通知的寄送結果': 'View delivery results for password resets and system notifications',
    '寄送狀態篩選': 'Delivery status filter',
    '寄送時間': 'Sent Time',
    '收件人': 'Recipient',
    '通知類型': 'Notification Type',
    '結果': 'Result',
    '失敗原因': 'Failure Reason',
    '讀取寄送紀錄中…': 'Loading delivery history…',
    '目前沒有符合條件的寄送紀錄': 'No matching delivery records',
    '忘記密碼': 'Password Reset',
    '測試郵件': 'Test Email',
    '設備離線通知': 'Device Offline Alert',
    '系統通知': 'System Notification',
    '寄送成功': 'Sent',
    '寄送失敗': 'Failed',
    '✉ 重新傳送': '✉ Resend',
    '寄送中…': 'Sending…',
    '傳送中…': 'Sending…',

    '人員管理｜SafeGuard': 'Personnel Management | SafeGuard',
    '新增時只需姓名與裝置，其他資料由系統自動更新': 'Only a name and device are required. Other data is updated automatically.',
    '下載匯入範例': 'Download Import Sample',
    '匯入 CSV': 'Import CSV',
    '＋ 新增人員': '+ Add Personnel',
    '員工姓名': 'Employee Name',
    '裝置名稱': 'Device Name',
    '位置': 'Location',
    '電量': 'Battery',
    '風險': 'Risk',
    '裝置狀態': 'Device Status',
    '新增人員': 'Add Personnel',
    '編輯人員': 'Edit Personnel',
    '輸入員工姓名並綁定裝置名稱。座標、電量、風險及狀態會由外部資料自動更新。': 'Enter an employee name and assign a device. Coordinates, battery, risk, and status are updated by external data.',
    '例如 王小明': 'Example: Wang Xiaoming',
    '儲存變更': 'Save Changes',
    '人員資料已更新': 'Personnel information updated',
    '人員已新增': 'Personnel added',
    '人員已移除': 'Personnel removed',
    '確定要移除此人員？': 'Are you sure you want to remove this person?',
    '目前尚無監控設備': 'No monitoring devices yet',

    '監控設備管理｜SafeGuard': 'Monitoring Device Management | SafeGuard',
    '監控設備管理': 'Monitoring Device Management',
    '管理攝影機裝置與安裝位置': 'Manage cameras and installation locations',
    '＋ 新增監控設備': '+ Add Monitoring Device',
    '裝置編號': 'Device ID',
    '最後更新': 'Last Updated',
    '串流網址': 'Stream URL',
    '新增監控設備': 'Add Monitoring Device',
    '編輯監控設備': 'Edit Monitoring Device',
    '建立攝影機裝置並設定安裝位置。': 'Create a camera device and set its installation location.',
    '串流網址（選填）': 'Stream URL (optional)',
    '新增設備': 'Add Device',
    '監控設備已更新': 'Monitoring device updated',
    '監控設備已新增': 'Monitoring device added',
    '監控設備已刪除': 'Monitoring device deleted',

    '設定區域｜SafeGuard': 'Area Settings | SafeGuard',
    '建立區域；每區固定 4 個 UWB 基站，座標與狀態可由外部 API 匯入': 'Create areas with exactly four UWB base stations each. Coordinates and status can be imported through an external API.',
    '前往 UWB 電子圍籬監看 →': 'Go to UWB Electronic Fence Monitoring →',
    '＋ 新增區域': '+ Add Area',
    '新增區域': 'Add Area',
    '輸入區域名稱即可建立。': 'Enter an area name to create it.',
    '區域名稱': 'Area Name',
    '例如 A 棟 1 樓': 'Example: Building A, Floor 1',
    '新增 UWB 基站': 'Add UWB Base Station',
    '例如 UWB 基站 A-01': 'Example: UWB Base Station A-01',
    'X 座標': 'X Coordinate',
    'Y 座標': 'Y Coordinate',
    'Z 座標': 'Z Coordinate',
    '新增基站': 'Add Base Station',
    '刪除區域': 'Delete Area',
    '目前尚無區域，請先新增區域。': 'No areas yet. Add an area first.',
    '目前尚無基站': 'No base stations yet',
    '位子': 'Position',
    '區域已新增': 'Area added',
    '區域已刪除': 'Area deleted',
    'UWB 基站已新增': 'UWB base station added',
    'UWB 基站已移除': 'UWB base station removed',
    '確定要移除此 UWB 基站？': 'Are you sure you want to remove this UWB base station?',
    '此操作無法復原。': 'This action cannot be undone.',

    'UWB 電子圍籬系統｜SafeGuard': 'UWB Electronic Fence System | SafeGuard',
    '請選擇監控區域以開始即時定位監看': 'Select a monitored area to start live location monitoring',
    '↻　資料來源：外部 UWB API': '↻ Data source: External UWB API',
    '每區固定 4 個基站': 'Exactly 4 base stations per area',
    '搜尋監控區域': 'Search monitored areas',
    '有警示': 'Has alerts',
    'ⓘ　區域來自設定區域；4 個基站的位置與狀態由外部 UWB 資料同步': 'ⓘ Areas come from Area Settings. Positions and status of the four base stations are synchronized from external UWB data.',
    '← 返回區域選擇': '← Back to Area Selection',
    'UWB 即時定位監看': 'Live UWB Location Monitoring',
    '每 5 秒同步一次定位資料': 'Location data synchronizes every 5 seconds',
    '越界／中高風險': 'Out of bounds / Medium-high risk',
    'UWB 基站': 'UWB Base Stations',
    '區域人員': 'Personnel in Area',
    '警示事件': 'Alert Events',
    '最後同步': 'Last Sync',
    '目前沒有符合條件的監控區域': 'No monitored areas match the current filter',
    '等待外部資料': 'Waiting for external data',
    '正常監控': 'Monitoring normally',
    '已同步 4 個基站': '4 base stations synchronized',
    '等待 4 個基站資料': 'Waiting for data from 4 base stations',
    '進入 UWB 監看': 'Open UWB Monitoring',
    '此區域已不存在': 'This area no longer exists',
    '拖曳更新位置；點擊切換風險': 'Drag to update location; click to change risk',
    '位置已儲存': 'Location saved',

    'YOLO 影像辨識串流｜SafeGuard': 'YOLO Vision Stream | SafeGuard',
    'YOLO 影像辨識串流': 'YOLO Vision Stream',
    '請選擇監控設備以開始即時辨識': 'Select a monitoring device to start live recognition',
    '搜尋監控設備': 'Search monitoring devices',
    'ⓘ　設備清單同步自監控設備設定': 'ⓘ The device list is synchronized from Monitoring Device Settings',
    '← 返回設備選擇': '← Back to Device Selection',
    '等待攝影機串流': 'Waiting for camera stream',
    '上傳測試影片': 'Upload Test Video',
    '選擇已上傳影片': 'Select Uploaded Video',
    '等待影像串流': 'Waiting for video stream',
    '請先在監控設備中設定串流網址，或上傳測試影片': 'Set a stream URL in Monitoring Devices or upload a test video.',
    '來源': 'Source',
    '尚未選擇攝影機': 'No camera selected',
    '辨識狀態': 'Recognition Status',
    '待機中': 'Standby',
    '監測項目': 'Detection Items',
    '安全帽、背心、人員': 'Helmet, vest, personnel',
    '目前沒有符合條件的監控設備': 'No monitoring devices match the current filter',
    '監視器即時影像': 'Live camera video',
    '點擊測試串流': 'Click to test stream',
    '尚未設定串流網址': 'Stream URL not configured',
    '正常連線': 'Connected',
    '串流網址：': 'Stream URL:',
    '進入 YOLO 串流': 'Open YOLO Stream',
    '選擇設備': 'Select Device',
    '正在連線攝影機串流…': 'Connecting to camera stream…',
    '正在連線攝影機': 'Connecting to camera',
    '等待影像來源': 'Waiting for video source',
    '攝影機串流播放中': 'Camera stream playing',
    '影像來源已連線（待串接 YOLO 模型）': 'Video source connected (YOLO model integration pending)',
    '無法播放此串流，請檢查網址與瀏覽器支援格式': 'Unable to play this stream. Check the URL and browser-supported format.',
    '攝影機串流連線失敗': 'Camera stream connection failed',
    '影像來源未連線': 'Video source disconnected',
    '此設備尚未設定串流網址，可至監控設備設定或上傳測試影片': 'This device has no stream URL. Configure it in Monitoring Devices or upload a test video.',
    '設備已選擇，尚未設定串流網址': 'Device selected; stream URL not configured',
    '影片已上傳': 'Video uploaded',
    '影片串流播放中': 'Video stream playing',

    'SQLite 資料庫｜SafeGuard': 'SQLite Database | SafeGuard',
    '實際操作': 'Live Operations',
    '資料表與最新紀錄': 'Tables and Latest Records',
    '正在讀取 SQLite 資訊…': 'Loading SQLite information…',
    '↻ 重新查詢': '↻ Query Again',
    '＋ 建立一筆報告測試資料': '+ Create Report Test Record',
    'SQLite 資料表': 'SQLite tables',
    '請選擇資料表': 'Select a table',
    '目前沒有資料': 'No data available',
    '無法讀取資料庫資訊': 'Unable to load database information',
    '已啟用': 'Enabled',
    '資料庫資料已重新查詢': 'Database data refreshed',
    '新增失敗': 'Add failed',
    '系統帳戶': 'System Accounts',
    'UWB 人員／標籤': 'UWB Personnel / Tags',
    '監控設備': 'Monitoring Devices',
    '設定區域': 'Area Settings',
    '通訊事件': 'Communication Events',
    '即時危險警報': 'Real-time Safety Alerts',

    '重設密碼｜SafeGuard': 'Reset Password | SafeGuard',
    '設定新密碼': 'Set a New Password',
    '請輸入至少 12 個字元的新密碼。完成後，此重設連結會立即失效。': 'Enter a new password with at least 12 characters. The reset link becomes invalid immediately after completion.',
    '新密碼': 'New Password',
    '至少 12 個字元': 'At least 12 characters',
    '再次輸入新密碼': 'Confirm New Password',
    '更新密碼': 'Update Password',
    '連結無效或已逾期': 'Invalid or Expired Link',
    '重設連結只能使用一次，並會在 10 分鐘後失效。請回到登入頁重新申請。': 'The reset link can only be used once and expires after 10 minutes. Return to the login page to request a new one.',

    '即時危險警報｜SafeGuard': 'Real-time Safety Alerts | SafeGuard',
    '集中查看 YOLO 影像辨識與 UWB 電子圍籬偵測的危險事件': 'View hazards detected by YOLO vision and UWB electronic fencing in one place',
    '發生時間': 'Time',
    '來源系統': 'Source',
    '區域／設備': 'Area / Device',
    '危險事件': 'Hazard Event',
    '等級': 'Severity',
    'LINE 通知': 'LINE Notification',
    'LINE：檢查中': 'LINE: Checking',
    'LINE：已連接': 'LINE: Connected',
    'LINE：尚未設定': 'LINE: Not Configured',
    '傳送 LINE 測試': 'Send LINE Test',
    '測試中…': 'Testing…',
    '已送出': 'Sent',
    '發送失敗': 'Failed',
    '尚未派送': 'Not Sent',
    '傳送中': 'Sending',
    '重新傳送': 'Resend',
    '嘗試': 'Attempts',
    'SafeGuard 系統測試': 'SafeGuard System Test',
    'LINE 即時危險警報連線測試': 'LINE Real-time Safety Alert Connection Test',
    '這是管理員手動建立的測試警報，無須前往現場。': 'This is an administrator-created test alert. No on-site response is required.',
    '尚未設定 Channel Access Token 或 LINE 通知對象': 'Channel access token or LINE recipient is not configured',
    'LINE 測試警報已送出': 'LINE test alert sent',
    '測試警報已建立，但尚未完成 LINE Messaging API 設定': 'Test alert created, but LINE Messaging API is not configured',
    'LINE 危險警報已重新傳送': 'LINE safety alert resent',
    '尚未完成 LINE Messaging API 設定': 'LINE Messaging API is not configured',
    'LINE 重新傳送失敗': 'Failed to resend LINE alert',
    'LINE 測試失敗': 'LINE test failed',
    'LINE：已連接，可確認警報': 'LINE: Connected, acknowledgement enabled',
    'LINE：可傳送，確認功能尚未啟用': 'LINE: Sending enabled, acknowledgement not configured',
    'LINE 已接收': 'Acknowledged in LINE',
    '等待接收': 'Awaiting acknowledgement',
    '警報尚未被確認': 'Alert has not been acknowledged',
    'LINE 使用者': 'LINE User',
    'LINE 接收狀態': 'LINE Acknowledgement',
    '接收人員': 'Acknowledged By',
    '接收時間': 'Acknowledged At',
    '未處理警報': 'Unresolved Alerts',
    '已完成事件': 'Completed Events',
    '搜尋事件、設備或位置': 'Search events, devices, or locations',
    '全部來源': 'All Sources',
    '全部日期': 'All Dates',
    '最近 7 天': 'Last 7 Days',
    '最近 30 天': 'Last 30 Days',
    '最近 90 天': 'Last 90 Days',
    '完成時間': 'Completed At',
    '事件內容': 'Event',
    '處理人員': 'Handled By',
    '處理備註': 'Resolution Note',
    '還原警報': 'Reopen Alert',
    '目前沒有已完成事件': 'No completed events',
    '標記完成的事件會永久保存在這裡': 'Completed events are permanently stored here.',
    '完成事件永久保存在 SQLite，可供事件追蹤與報告使用': 'Completed events are permanently stored in SQLite for tracking and reports.',
    '完成事件': 'Complete Event',
    '記錄事件處理結果': 'Record Resolution',
    '例如：已確認人員安全，完成現場紀錄': 'Example: Personnel safety confirmed and on-site record completed',
    '確認完成': 'Confirm Completion',
    '事件詳情': 'Event Details',
    '設備編號': 'Device ID',
    '危險等級': 'Severity',
    '詳細說明': 'Details',
    '系統管理員': 'System Administrator',
    '已完成事件處理': 'Event handling completed',
    '還原失敗': 'Failed to reopen alert',
    '確定要將此事件還原為未處理警報嗎？': 'Reopen this event as an unresolved alert?',
    '危險警報已標記為已處理': 'Safety alert marked as resolved',
    '事件已還原為未處理警報': 'Event reopened as an unresolved alert',
    '找不到此未處理警報': 'Unresolved alert not found',
    '找不到此已完成事件': 'Completed event not found',
    '警報狀態': 'Alert Status',
    '來源篩選': 'Source Filter',
    '日期篩選': 'Date Filter',
    '正在載入危險警報…': 'Loading safety alerts…',
    '頁面每 15 秒自動更新': 'Automatically refreshes every 15 seconds',
    'YOLO 影像辨識': 'YOLO Vision',
    'UWB 電子圍籬': 'UWB E-Fence',
    '查看影像': 'View Video',
    '查看位置': 'View Location',
    '查看詳情': 'View Details',
    '其他系統': 'Other System',
    '目前沒有危險警報': 'No safety alerts',
    'YOLO 或 UWB 偵測到危險事件後會顯示在這裡': 'Hazards detected by YOLO or UWB will appear here.',
    '標記已處理': 'Mark Resolved',
    '未設定位置': 'Location not configured',
    '危險警報載入失敗': 'Unable to load safety alerts',
    '更新失敗': 'Update failed',
    '偵測到人員未配戴安全帽': 'Worker detected without a safety helmet',
    '人員進入危險電子圍籬': 'Worker entered a hazardous geofence',
    '人員與移動機具距離過近': 'Worker is too close to moving equipment',
    '人員未穿著反光背心': 'Worker detected without a reflective vest',
    '人員離開安全活動範圍': 'Worker left the safe activity range',
    '工地入口': 'Site Entrance',
    'A 棟 1 樓禁入區': 'Building A, Floor 1 Restricted Area',
    '卸料區': 'Unloading Area',
    '高處作業區': 'Work-at-Height Area'
  });

  const textOriginal = new WeakMap();
  const textApplied = new WeakMap();
  const attributeState = new WeakMap();
  let currentLanguage = SUPPORTED_LANGUAGES.has(localStorage.getItem(STORAGE_KEY))
    ? localStorage.getItem(STORAGE_KEY)
    : DEFAULT_LANGUAGE;
  let observer = null;

  function translatePattern(text) {
    const rules = [
      [/^(\d+) 筆未處理$/, '$1 unresolved'],
      [/^(\d+) 筆越界警示$/, '$1 boundary alerts'],
      [/^(\d+) 個基站離線$/, '$1 base stations offline'],
      [/^(\d+) 筆$/, '$1 records'],
      [/^(\d+) 人$/, '$1 people'],
      [/^(\d+) 位人員$/, '$1 people'],
      [/^(\d+) 支$/, '$1 cameras'],
      [/^(\d+) 分鐘前$/, '$1 minutes ago'],
      [/^(\d+) 小時前$/, '$1 hours ago'],
      [/^(\d+) 天前$/, '$1 days ago'],
      [/^最後更新：剛剛$/, 'Last updated: Just now'],
      [/^最後更新：(\d+) 分鐘前$/, 'Last updated: $1 minutes ago'],
      [/^最後更新：(\d+) 小時前$/, 'Last updated: $1 hours ago'],
      [/^最後更新：(\d+) 天前$/, 'Last updated: $1 days ago'],
      [/^最後匯入：剛剛$/, 'Last import: Just now'],
      [/^最後匯入：(\d+) 分鐘前$/, 'Last import: $1 minutes ago'],
      [/^最後匯入：(\d+) 小時前$/, 'Last import: $1 hours ago'],
      [/^最後匯入：(\d+) 天前$/, 'Last import: $1 days ago'],
      [/^最後更新：(.+)$/, 'Last updated: $1'],
      [/^最後匯入：(.+)$/, 'Last import: $1'],
      [/^重複 (\d+) 次$/, 'Repeated $1 times'],
      [/^・重複 (\d+) 次$/, ' · Repeated $1 times'],
      [/^發生於 (.+)$/, 'Occurred at $1'],
      [/^已接收警報 #(\d+)：(.+)$/, 'Alert #$1 acknowledged: $2'],
      [/^警報 #(\d+) 已由 (.+) 接收$/, 'Alert #$1 was acknowledged by $2'],
      [/^警報 #(\d+) 已完成處理$/, 'Alert #$1 has already been resolved'],
      [/^找不到警報 #(\d+)$/, 'Alert #$1 not found'],
      [/^(\d+) \/ 4 正常$/, '$1 / 4 online'],
      [/^偵測到 (\d+) 筆注意或越界事件$/, '$1 attention or boundary alerts detected'],
      [/^新增 UWB 基站｜(.+)$/, 'Add UWB Base Station | $1'],
      [/^(.+)｜UWB 即時定位監看$/, '$1 | Live UWB Location Monitoring'],
      [/^確定要刪除監控設備 (.+)？$/, 'Are you sure you want to delete monitoring device $1?'],
      [/^此區域內有 (\d+) 個 UWB 基站，刪除區域時也會一併刪除。$/, 'This area contains $1 UWB base stations. Deleting the area will also delete them.'],
      [/^確定要刪除區域「(.+)」？$/, 'Are you sure you want to delete area "$1"?'],
      [/^風險已更新為 (.+)$/, 'Risk updated to $1'],
      [/^已匯入或更新 (\d+) 筆(.+)$/, 'Imported or updated $1 records$2'],
      [/^；略過第 (.+) 行$/, '; skipped rows $1'],
      [/^外鍵約束：已啟用｜Journal：(.+)｜更新：(.+)$/, 'Foreign keys: Enabled | Journal: $1 | Updated: $2'],
      [/^外鍵約束：未啟用｜Journal：(.+)｜更新：(.+)$/, 'Foreign keys: Disabled | Journal: $1 | Updated: $2'],
      [/^(.+)，資料列 ID：(.+)$/, '$1, row ID: $2'],
      [/^測試信失敗：(.+)$/, 'Test email failed: $1'],
      [/^重新傳送失敗：(.+)$/, 'Resend failed: $1'],
      [/^人員 (.+)・信心度 (.+)$/, 'Worker $1 · Confidence $2'],
      [/^人員 (.+)・停留 (.+) 秒$/, 'Worker $1 · Inside for $2 sec'],
      [/^人員 (.+)・距離 (.+) 公尺$/, 'Worker $1 · Distance $2 m'],
      [/^人員 (.+)・超出範圍 (.+) 秒$/, 'Worker $1 · Outside range for $2 sec'],
      [/^人員／標籤 (.+)・座標 X (.+) \/ Y (.+) \/ Z (.+)・電量 (.+)%$/, 'Worker / tag $1 · Coordinates X $2 / Y $3 / Z $4 · Battery $5%'],
      [/^人員／裝置 (.+)・信心度 (.+)$/, 'Worker / device $1 · Confidence $2']
    ];
    for (const [pattern, replacement] of rules) {
      if (pattern.test(text)) return text.replace(pattern, replacement);
    }
    return ENGLISH[text] || text;
  }

  function translateValue(value) {
    if (currentLanguage !== 'en' || typeof value !== 'string') return value;
    const match = value.match(/^(\s*)([\s\S]*?)(\s*)$/);
    if (!match || !match[2]) return value;
    return `${match[1]}${translatePattern(match[2])}${match[3]}`;
  }

  function isSkipped(node) {
    const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
    return !element || Boolean(element.closest('script,style,code,pre,textarea,[data-i18n-skip]'));
  }

  function translateTextNode(node) {
    if (isSkipped(node) || !node.nodeValue || !node.nodeValue.trim()) return;
    const current = node.nodeValue;
    if (!textOriginal.has(node) || current !== textApplied.get(node)) {
      textOriginal.set(node, current);
    }
    const original = textOriginal.get(node);
    const translated = currentLanguage === 'en' ? translateValue(original) : original;
    textApplied.set(node, translated);
    if (current !== translated) node.nodeValue = translated;
  }

  function translateAttributes(element) {
    if (!(element instanceof Element) || isSkipped(element)) return;
    let state = attributeState.get(element);
    if (!state) {
      state = {};
      attributeState.set(element, state);
    }
    ['placeholder', 'title', 'aria-label'].forEach(attribute => {
      if (!element.hasAttribute(attribute)) return;
      const current = element.getAttribute(attribute);
      const item = state[attribute] || {};
      if (!('original' in item) || current !== item.applied) item.original = current;
      item.applied = currentLanguage === 'en' ? translateValue(item.original) : item.original;
      state[attribute] = item;
      if (current !== item.applied) element.setAttribute(attribute, item.applied);
    });
  }

  function translateTree(root = document) {
    if (root.nodeType === Node.TEXT_NODE) {
      translateTextNode(root);
      return;
    }
    if (root.nodeType === Node.ELEMENT_NODE && isSkipped(root)) return;
    if (root.nodeType === Node.ELEMENT_NODE) translateAttributes(root);
    const textWalker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let textNode;
    while ((textNode = textWalker.nextNode())) translateTextNode(textNode);
    const elements = root.querySelectorAll ? root.querySelectorAll('*') : [];
    elements.forEach(translateAttributes);
  }

  function applyTranslations(root = document) {
    translateTree(root);
    if (!document.documentElement.dataset.originalTitle) {
      document.documentElement.dataset.originalTitle = document.title;
    }
    document.title = currentLanguage === 'en'
      ? translatePattern(document.documentElement.dataset.originalTitle)
      : document.documentElement.dataset.originalTitle;
    document.documentElement.lang = currentLanguage;
    document.querySelectorAll('[data-language-select]').forEach(select => {
      if (select.value !== currentLanguage) select.value = currentLanguage;
    });
  }

  function setLanguage(language) {
    currentLanguage = SUPPORTED_LANGUAGES.has(language) ? language : DEFAULT_LANGUAGE;
    localStorage.setItem(STORAGE_KEY, currentLanguage);
    applyTranslations(document);
    window.dispatchEvent(new CustomEvent('safeguard:languagechange', {detail: {language: currentLanguage}}));
  }

  const nativeConfirm = window.confirm.bind(window);
  const nativeAlert = window.alert.bind(window);
  window.confirm = message => nativeConfirm(currentLanguage === 'en' ? translateValue(String(message)) : message);
  window.alert = message => nativeAlert(currentLanguage === 'en' ? translateValue(String(message)) : message);

  window.SafeGuardI18n = {
    t: value => currentLanguage === 'en' ? translateValue(String(value ?? '')) : String(value ?? ''),
    setLanguage,
    applyTranslations,
    get language() { return currentLanguage; }
  };

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-language-select]').forEach(select => {
      select.value = currentLanguage;
      select.addEventListener('change', event => setLanguage(event.target.value));
    });
    applyTranslations(document);
    observer = new MutationObserver(mutations => {
      mutations.forEach(mutation => {
        if (mutation.type === 'characterData') {
          translateTextNode(mutation.target);
          return;
        }
        mutation.addedNodes.forEach(translateTree);
        if (mutation.type === 'attributes') translateAttributes(mutation.target);
      });
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ['placeholder', 'title', 'aria-label']
    });
  });
})();
