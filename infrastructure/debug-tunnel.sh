#!/bin/bash

# --- GLOBAL CONFIG ---
CLUSTER_NAME="eo-agent-2-cluster"
REGION="eu-west-1"
INFRA_PROFILE="InfraAdmin-963275461308" # Added your InfraAdmin profile here
# ---------------------

# If no arguments are provided, default to running all three services
if [ $# -eq 0 ]; then
    SERVICES=("mcp" "agent" "streamlit")
else
    SERVICES=("$@")
fi

# Validate arguments before doing anything
for SVC in "${SERVICES[@]}"; do
    if [[ "$SVC" != "mcp" && "$SVC" != "agent" && "$SVC" != "streamlit" ]]; then
        echo "❌ Error: Invalid service '$SVC'."
        echo "👉 Usage: $0 [mcp] [agent] [streamlit] (or leave empty to run all 3)"
        exit 1
    fi
done

# Function to handle the SSM tunneling logic for a specific service
start_tunnel() {
    local SERVICE_KEY=$1
    local LOCAL_PORT=""
    local CONTAINER_PORT=""
    local SERVICE_NAME=""

    # Map services to their specific ports and ECS Service Names
    # ⚠️ Adjust SERVICE_NAME mappings below if your actual ECS names differ!
    case "$SERVICE_KEY" in
        mcp)
            LOCAL_PORT="5677"
            CONTAINER_PORT="5678" 
            SERVICE_NAME="eo-agent-2-mcp-service"
            ;;
        agent)
            LOCAL_PORT="5678"
            CONTAINER_PORT="5678"
            SERVICE_NAME="eo-agent-2-agent-service"
            ;;
        streamlit)
            LOCAL_PORT="5679"
            CONTAINER_PORT="5678"
            SERVICE_NAME="eo-agent-2-streamlit-service"
            ;;
    esac

    echo "🔍 [$SERVICE_KEY] Fetching active Task ID for $SERVICE_NAME..."
    # Added --profile flag
    TASK_ARN=$(aws ecs list-tasks --cluster "$CLUSTER_NAME" --service-name "$SERVICE_NAME" --region "$REGION" --profile "$INFRA_PROFILE" --query "taskArns[0]" --output text)

    if [ "$TASK_ARN" == "None" ] || [ -z "$TASK_ARN" ]; then
        echo "❌ [$SERVICE_KEY] Error: No running tasks found for service $SERVICE_NAME"
        return 1
    fi

    TASK_ID=$(echo "$TASK_ARN" | awk -F/ '{print $NF}')
    echo "🎯 [$SERVICE_KEY] Found Task ID: $TASK_ID"

    echo "🔍 [$SERVICE_KEY] Fetching Container Runtime ID..."
    # Added --profile flag
    RUNTIME_ID=$(aws ecs describe-tasks --cluster "$CLUSTER_NAME" --tasks "$TASK_ID" --region "$REGION" --profile "$INFRA_PROFILE" --query "tasks[0].containers[0].runtimeId" --output text)

    if [ "$RUNTIME_ID" == "None" ] || [ -z "$RUNTIME_ID" ]; then
        echo "❌ [$SERVICE_KEY] Error: Could not retrieve container runtime ID."
        return 1
    fi
    echo "🎯 [$SERVICE_KEY] Found Runtime ID: $RUNTIME_ID"

    TARGET_STRING="ecs:${CLUSTER_NAME}_${TASK_ID}_${RUNTIME_ID}"
    echo "🚀 [$SERVICE_KEY] Opening secure SSM tunnel (Local $LOCAL_PORT -> Container $CONTAINER_PORT)..."

    # Running in the background (&) so multiple services can run concurrently
    # Added --profile flag
    aws ssm start-session \
        --region "$REGION" \
        --target "$TARGET_STRING" \
        --document-name AWS-StartPortForwardingSession \
        --profile "$INFRA_PROFILE" \
        --parameters "{\"portNumber\":[\"$CONTAINER_PORT\"],\"localPortNumber\":[\"$LOCAL_PORT\"]}" &
}

# Trap configuration: Killing the script will automatically terminate all background SSM tunnels
trap 'echo -e "\n🛑 Stopping all tunnels..."; kill $(jobs -p) 2>/dev/null; wait; echo "✅ All tunnels closed."' EXIT INT TERM

# Launch the requested services
for SVC in "${SERVICES[@]}"; do
    start_tunnel "$SVC"
    sleep 1.5 # Brief pause to prevent overlapping log text and AWS throttling
done

echo "🟢 Tunnels are active. Press [Ctrl+C] to exit and close all connections."

# Keep the main script thread alive while background jobs run
wait