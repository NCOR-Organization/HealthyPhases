"""The workspace assistant: what it can read and do in the HealthyPhases app.

``workspace`` holds the actions, as thin wrappers over the application services
the app's endpoints use; ``tools`` exposes them to the assistant; and
``confirmations`` holds the guard every costly action must pass. The agent
itself, which Nexus loads in its right pane, lives in ``phases_v2.agents``.
"""
