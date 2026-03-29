"""
Preview-tool entry point — sets up sys.path and cwd so Flask can be
started from any working directory.
"""
import sys
import os

# Ensure the project root is on the path regardless of cwd at launch time
project_root = os.path.dirname(os.path.abspath(__file__))
os.chdir(project_root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
