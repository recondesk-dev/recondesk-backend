import subprocess
import re

res = subprocess.run(["pytest", "-q", "--tb=short"], capture_output=True, text=True)
print(res.stdout)
