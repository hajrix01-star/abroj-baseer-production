"""Source-only GitHub preparation for the separately verified IC2 R2 source."""
import ic2_recovery  # Sets the release identity before the exporter imports it.
from ic2_github_sync import prepare

if __name__ == '__main__':
    prepare()
