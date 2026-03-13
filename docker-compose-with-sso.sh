#!/bin/bash
# Helper script to run docker-compose with AWS SSO credentials
# Usage: ./docker-compose-with-sso.sh [docker-compose args]
# Example: ./docker-compose-with-sso.sh up
# Example: ./docker-compose-with-sso.sh up -d agent-server

set -e

PROFILE="${AWS_PROFILE:-gaia-amine}"

echo "🔐 Exporting AWS SSO credentials from profile: $PROFILE"

# Check if profile exists and is authenticated
if ! aws sts get-caller-identity --profile "$PROFILE" &> /dev/null; then
    echo "❌ Failed to authenticate with profile: $PROFILE"
    echo ""
    echo "Please run: aws sso login --profile $PROFILE"
    exit 1
fi

echo "✅ AWS SSO session is valid"
echo ""

# Export credentials
echo "📦 Exporting credentials..."
export AWS_ACCESS_KEY_ID=$(aws configure get aws_access_key_id --profile "$PROFILE")
export AWS_SECRET_ACCESS_KEY=$(aws configure get aws_secret_access_key --profile "$PROFILE")
export AWS_SESSION_TOKEN=$(aws configure get aws_session_token --profile "$PROFILE")
export AWS_REGION=eu-west-3

if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
    echo "❌ Failed to export credentials. Check your AWS configuration."
    exit 1
fi

echo "✅ Credentials exported successfully"
echo ""
echo "🚀 Running docker-compose $@"
echo ""

# Run docker-compose with all arguments passed to this script
docker-compose "$@"
