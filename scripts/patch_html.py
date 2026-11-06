with open('finsight_corporate_workspace.html', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('Grafik G\xf6r\xfcn\xfcm\xfc', 'Grafik G&ouml;r&uuml;n&uuml;m&uuml;')

api_def = """        // API Base Resolution (Direct or via FastAPI backend)
        const API_BASE = (window.location.protocol.startsWith("http") && window.location.port === "8000") ? "" : "http://127.0.0.1:8000";
"""
if "const API_BASE" not in c:
    c = c.replace('// Active State', api_def + '\n        // Active State')

c = c.replace('const url = `/api/orchestrate?ticker=${encodeURIComponent(symbol)}`;', 'const url = `${API_BASE}/api/orchestrate?ticker=${encodeURIComponent(symbol)}`;')
c = c.replace("fetch('/api/guardrail/check'", "fetch(API_BASE + '/api/guardrail/check'")

with open('finsight_corporate_workspace.html', 'w', encoding='utf-8') as f:
    f.write(c)

with open('demo/index.html', 'w', encoding='utf-8') as f:
    f.write(c)

print('Updated finsight_corporate_workspace.html & demo/index.html successfully')

