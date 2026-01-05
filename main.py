# Buildpack entrypoint placeholder.
# Cloud Run JOB uses --command/--args; this file exists only so buildpacks detect a Python entrypoint.
if __name__ == "__main__":
    print("agenttrader buildpack entrypoint OK")
