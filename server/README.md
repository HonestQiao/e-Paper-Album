# EPD E-Paper Image Management System

E-Paper Display image management system, providing Web interface management and Socket network communication services.

## 📋 Core File Descriptions

### 1. manage.py
**Unified Management System Entry Point**

- **Function**: Unified startup and management of Web and Socket services
- **Purpose**: Main project entry point, supports three running modes
- **Startup Methods**:
  ```bash
  # Start all services (recommended)
  python manage.py --mode all

  # Start Web service only
  python manage.py --mode web

  # Start Socket service only
  python manage.py --mode socket

  # Custom ports and directories
  python manage.py --mode all --web-port 5000 --socket-port 18888 --image-dir ./dist/data
  ```

### 2. web_server.py
**Web Management Interface**

- **Function**: Provides Web interface for image upload, preview, and management
- **Purpose**: Browser access, graphical management interface, supports image format conversion
- **Startup Methods**:
  ```bash
  # Use default configuration (port 5000)
  python web_server.py

  # Custom host and port
  python web_server.py --host 0.0.0.0 --port 5000
  ```

### 3. epd_socket_server.py
**Socket Server**

- **Function**: Listen for TCP connections, process client commands, return image data
- **Purpose**: Communicate with E-Paper device, support file monitoring and automatic image list updates
- **Startup Methods**:
  ```bash
  # Use default configuration (port 18888)
  python epd_socket_server.py

  # Specify image directory
  python epd_socket_server.py --image-dir ./dist/data

  # Custom host and port
  python epd_socket_server.py --host 0.0.0.0 --port 18888
  ```

### 4. epd_socket_client.py
**Socket Client (Test Tool)**

- **Function**: Connect to Socket server, send commands to test services
- **Purpose**: Debug and test Socket server functionality
- **Startup Methods**:
  ```bash
  # Interactive mode
  python epd_socket_client.py

  # Send command (non-interactive)
  python epd_socket_client.py update

  # Download current image
  python epd_socket_client.py get -o ./downloaded

  # Download using C array format
  python epd_socket_client.py get_c

  # Custom server address
  python epd_socket_client.py --host 127.0.0.1 --port 18888 status
  ```

## 🚀 Quick Start

### Method 1: Unified Startup (Recommended)
```bash
python manage.py --mode all --image-dir ./dist/data
```

### Method 2: Separate Startup
```bash
# Terminal 1: Start Web service
python web_server.py

# Terminal 2: Start Socket service
python epd_socket_server.py --image-dir ./dist/data
```

### Method 3: Test Connection
```bash
# Test Socket server
python epd_socket_client.py update
python epd_socket_client.py list
```

## 📊 System Architecture

```
┌─────────────────┐
│   Web Browser   │──┐
└─────────────────┘  │
                     │ HTTP (5000)
┌─────────────────┐  │
│  web_server.py  │  │
│  (Flask Web)    │  │
└─────────────────┘  │
                     │
┌─────────────────┐  │
│   manage.py     │──┘
└─────────────────┘
         │
         │ TCP (18888)
         │
┌─────────────────┐
│epd_socket_server│
│   .py           │
└─────────────────┘
         │
         │ File Monitoring
         │
┌─────────────────┐
│   ./dist/data   │
│   (BMP Images)  │
└─────────────────┘

┌─────────────────┐
│epd_socket_client│
│   .py           │
│  (Test Client)  │
└─────────────────┘
```

## 🔧 Main Features

### Web Management Interface
- Image upload (JPG, PNG, BMP, GIF)
- Automatic conversion to BMP format
- Image preview and management
- Real-time conversion progress display
- **Multi-language Support**: Switch between Chinese (Simplified), Chinese (Traditional), and English via the language dropdown in the top-right corner

### Socket Server
- Listen on port 18888
- Support commands: `update`, `info`, `get`, `get_c`, `list`
- File monitoring: Auto-detect BMP image changes
- 5-second debounce mechanism: Prevent frequent updates
- Filename sorting: Support numeric filename sorting

### File Monitoring Features
- Auto-scan BMP files in `dist/data` directory
- File modification time + size checksum for change detection
- 5-second debounce delay after changes
- Automatic reload of image list

## ⚙️ Configuration

### Default Ports
- **Web Service**: 5000
- **Socket Service**: 18888

### Default Directories
- **Image Directory**: `./dist/data`
- **Upload Directory**: `./uploads`

### Supported Image Formats
- Input: JPG, JPEG, PNG, GIF, BMP
- Output: BMP (for E-Paper display)

## 📝 Dependency Installation

```bash
pip install -r requirements.txt
```

Or install separately:
```bash
pip install "Flask>=2.3.0" "Pillow>=10.0.0"
```

## 🌍 Multi-language Support

The Web interface supports multiple languages:

- **Chinese (Simplified)** - 中文(简体)
- **Chinese (Traditional)** - 中文(繁體)
- **English** - English

### Switching Languages
Click the language dropdown button in the top-right corner of the Web interface to switch languages. The language preference is saved in cookies and will be automatically restored on your next visit.

### Adding New Languages

1. Create a new JSON file in `static/locales/` (e.g., `ja.json` for Japanese):
   ```bash
   cp static/locales/en.json static/locales/ja.json
   ```

2. Translate the content in the new file

3. Add the new language to `supportedLangs` array in `templates/index.html`:
   ```javascript
   supportedLangs: ['zh-CN', 'zh-TW', 'en', 'ja'],
   ```

4. Add the language option to the dropdown menu in `templates/index.html`:
   ```html
   <li><a class="dropdown-item" href="#" onclick="setLanguage('ja')" data-lang="ja">日本語</a></li>
   ```

5. Add the language name to all language files under the `languages` key:
   ```json
   "languages": {
       "zh-CN": "中文(简体)",
       "zh-TW": "中文(繁體)",
       "en": "English",
       "ja": "日本語"
   }
   ```

## 📡 API Endpoints

### Web Server API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web interface homepage |
| `/api/images` | GET | Get list of BMP images |
| `/api/uploads` | GET | Get list of uploaded files |
| `/api/upload` | POST | Upload new images |
| `/api/convert` | POST | Convert image to BMP |
| `/api/delete` | POST | Delete uploaded file |
| `/api/delete-bmp` | POST | Delete BMP file |
| `/api/batch_convert` | POST | Batch convert images |
| `/api/batch_delete` | POST | Batch delete images |
| `/api/progress/<filename>` | GET | Get conversion progress |
| `/api/refresh` | GET | Refresh image list |

### Socket Server Protocol

**Connection**: TCP on port 18888

**Command Format**: Send command string followed by newline

**Commands**:
- `update` - Get next image index and switch
- `info` - Get current image information
- `get` - Get current image binary data (BMP)
- `get_c` - Get current image as C array
- `list` - Get list of all images

**Response Format** (JSON):
```json
{
    "success": true,
    "data": { ... }
}
```

## 🔍 Debugging

### Check Service Status
```bash
# Check if ports are listening
netstat -an | grep -E '5000|18888'

# Check process
ps aux | grep python
```

### View Logs
- Server logs are output to console by default
- Log files can be configured with `--log-file` option

### Test Socket Connection
```bash
# Using netcat
nc localhost 18888

# Then type command and press Enter:
# update
# info
# list
```
