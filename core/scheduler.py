import random
from datetime import datetime, timedelta

def schedule_smart(count, interval_range=(5, 30)):
    intervals = []
    for _ in range(count):
        intervals.append(random.randint(*interval_range))
    return intervals

def schedule_manual(count, fixed_delay):
    return [fixed_delay] * count

def schedule_ai_optimized(count, target_hour=None):
    intervals = []
    base_delay = random.randint(10, 60)
    for i in range(count):
        jitter = random.uniform(-0.3, 0.3)
        delay = max(1, int(base_delay * (1 + jitter)))
        intervals.append(delay)
        if i % 5 == 0:
            base_delay = random.randint(30, 120)
    return intervals

def calculate_eta(count, delays):
    total_sec = sum(delays)
    return str(timedelta(seconds=total_sec))
