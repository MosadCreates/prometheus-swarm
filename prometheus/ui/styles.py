from prometheus.ui.theme import Theme


class Token:
    accent = str(Theme.accent)
    highlight = str(Theme.highlight)
    secondary_accent = str(Theme.secondary_accent)

    primary = str(Theme.primary)
    secondary = str(Theme.secondary)
    border = str(Theme.border)

    heading = str(Theme.heading)
    success = str(Theme.success)
    warning = str(Theme.warning)
    error = str(Theme.error)
    command = str(Theme.command)

    status_text = str(Theme.status_text)
    info = str(Theme.info)
    dim = "dim white"
    white = "white"
    muted = "dim italic"
    muted_line = str(Theme.muted)
