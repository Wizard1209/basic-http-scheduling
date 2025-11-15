#!/bin/bash
# Redis Queue Data Loss Debug Script
# Run this IMMEDIATELY when you notice the queue is empty

# Generate timestamped filename
LOGFILE="redis-debug-$(date +%Y%m%d-%H%M%S).log"

# Function to run all debug commands
run_debug() {
    echo "=== Redis Queue Data Loss Debug ==="
    echo "Timestamp: $(date -Iseconds)"
    echo ""

    echo "=== 1. Queue Status ==="
    docker exec basic-http-scheduling-redis redis-cli ZCARD queue
    docker exec basic-http-scheduling-redis redis-cli ZRANGE queue 0 5 WITHSCORES
    echo ""

    echo "=== 2. Database Size ==="
    docker exec basic-http-scheduling-redis redis-cli DBSIZE
    docker exec basic-http-scheduling-redis redis-cli KEYS '*'
    echo ""

    echo "=== 3. Command Statistics ==="
    docker exec basic-http-scheduling-redis redis-cli INFO commandstats
    echo ""

    echo "=== 4. Persistence Info ==="
    docker exec basic-http-scheduling-redis redis-cli INFO persistence
    echo ""

    echo "=== 5. Last Save Time ==="
    docker exec basic-http-scheduling-redis redis-cli LASTSAVE
    echo ""

    echo "=== 6. Slow Log (last 50 commands) ==="
    docker exec basic-http-scheduling-redis redis-cli SLOWLOG GET 50
    echo ""

    echo "=== 7. Recent App Logs (last 30 min) ==="
    docker compose logs app --since 30m --tail 100
    echo ""

    echo "=== 8. Recent Redis Logs (last 30 min) ==="
    docker compose logs redis --since 30m
    echo ""
}

# Run debug commands and save to file (also display on screen)
run_debug 2>&1 | tee "$LOGFILE"

echo ""
echo "✓ Debug report saved to: $LOGFILE"
