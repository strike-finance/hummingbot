#!/bin/bash
# Dynamic Hummingbot multi-bot launcher
# Usage: ./run_bots.sh start|stop|status|logs [pair]

IMAGE_NAME="hummingbot:latest"
PAIRS=("btc" "eth" "sol" "ada")  # Add your 100 pairs here

# Or load from a file:
# PAIRS=($(cat pairs.txt))

start_bot() {
    local pair=$1
    local container_name="hummingbot-${pair}"
    
    # Check if already running
    if docker ps -q -f name="^${container_name}$" | grep -q .; then
        echo "⚠️  ${container_name} is already running"
        return
    fi
    
    echo "🚀 Starting ${container_name}..."
    docker run -d \
        --name "${container_name}" \
        --network host \
        --restart unless-stopped \
        -e CONFIG_FILE_NAME="${pair}_usd_mm.yml" \
        -v "$(pwd)/conf:/home/hummingbot/conf" \
        -v "$(pwd)/logs/${pair}:/home/hummingbot/logs" \
        -v "$(pwd)/data/${pair}:/home/hummingbot/data" \
        -v "$(pwd)/scripts:/home/hummingbot/scripts" \
        -v "$(pwd)/controllers:/home/hummingbot/controllers" \
        -t \
        "${IMAGE_NAME}"
}

stop_bot() {
    local pair=$1
    local container_name="hummingbot-${pair}"
    echo "🛑 Stopping ${container_name}..."
    docker stop "${container_name}" 2>/dev/null && docker rm "${container_name}" 2>/dev/null
}

case "$1" in
    start)
        if [ -n "$2" ]; then
            start_bot "$2"
        else
            for pair in "${PAIRS[@]}"; do
                start_bot "$pair"
            done
        fi
        ;;
    stop)
        if [ -n "$2" ]; then
            stop_bot "$2"
        else
            for pair in "${PAIRS[@]}"; do
                stop_bot "$pair"
            done
        fi
        ;;
    status)
        echo "📊 Hummingbot containers:"
        docker ps -a --filter "name=hummingbot-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
        ;;
    logs)
        if [ -n "$2" ]; then
            docker logs -f "hummingbot-${2}"
        else
            echo "Usage: $0 logs <pair>"
        fi
        ;;
    build)
        echo "🔨 Building hummingbot image..."
        docker build -t "${IMAGE_NAME}" .
        ;;
    *)
        echo "Usage: $0 {start|stop|status|logs|build} [pair]"
        echo ""
        echo "Examples:"
        echo "  $0 build          # Build image once"
        echo "  $0 start          # Start all bots"
        echo "  $0 start btc      # Start only BTC bot"
        echo "  $0 stop           # Stop all bots"
        echo "  $0 status         # Show all bot statuses"
        echo "  $0 logs eth       # Follow ETH bot logs"
        exit 1
        ;;
esac

