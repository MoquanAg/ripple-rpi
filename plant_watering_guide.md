# Hydroponic Watering Schedule for Your Plants

## Current Setup Analysis
- **Pea Shoots**: Just germinated in trays (high moisture needs, sensitive to overwatering)
- **Tomatoes & Peppers**: Young plants in substrate cups (moderate to high water needs)

## Optimal Watering Schedules

### 🌱 **Pea Shoots (Germination Stage)**
**Critical Period**: First 7-10 days after germination

- **Frequency**: Every 2-3 hours during daylight (8am-8pm)
- **Duration**: 2-3 minutes per cycle
- **Daily Cycles**: 4-6 times per day
- **Total Daily Watering**: 8-18 minutes

**Configuration for Pea Shoots**:
```ini
sprinkler_on_duration = 00:02:30    # 2.5 minutes
sprinkler_wait_duration = 02:30:00   # 2.5 hours between cycles
```

### 🍅🌶️ **Tomatoes & Peppers (Young Plants)**
**Stage**: Seedlings to early vegetative growth in substrate

- **Frequency**: Every 4-6 hours during daylight
- **Duration**: 3-5 minutes per cycle  
- **Daily Cycles**: 3-4 times per day
- **Total Daily Watering**: 9-20 minutes

**Configuration for Tomatoes/Peppers**:
```ini
sprinkler_on_duration = 00:04:00    # 4 minutes
sprinkler_wait_duration = 05:00:00   # 5 hours between cycles
```

## **Recommended Compromise Schedule**

Since you're growing both types together, here's a balanced approach:

### **Current Growth Stage Schedule**
```ini
[Sprinkler]
sprinkler_on_duration = 01:10:00, 00:03:00    # 3 minutes ON
sprinkler_wait_duration = 03:00:00, 03:00:00   # 3 hours WAIT
```

**This gives you**:
- **8 cycles per day** (every 3 hours)
- **24 minutes total daily watering**
- **Runs at**: 6am, 9am, 12pm, 3pm, 6pm, 9pm, 12am, 3am

## **Stage-Based Adjustments**

### **Week 1-2: Germination Focus**
```ini
sprinkler_on_duration = 01:10:00, 00:02:00    # 2 minutes (gentle for pea shoots)
sprinkler_wait_duration = 03:00:00, 02:00:00   # 2 hours (more frequent)
```

### **Week 3-4: Balanced Growth**  
```ini
sprinkler_on_duration = 01:10:00, 00:03:00    # 3 minutes
sprinkler_wait_duration = 03:00:00, 03:00:00   # 3 hours
```

### **Week 5+: Mature Plant Focus**
```ini
sprinkler_on_duration = 01:10:00, 00:04:00    # 4 minutes (more for tomatoes/peppers)
sprinkler_wait_duration = 03:00:00, 04:00:00   # 4 hours (less frequent but longer)
```

## **Environmental Adjustments**

### **Hot Weather** (>25°C/77°F)
- Reduce wait time by 30-60 minutes
- Increase duration by 30-60 seconds

### **Cool Weather** (<18°C/64°F)  
- Increase wait time by 60-90 minutes
- Keep duration the same or reduce slightly

### **High Humidity** (>70%)
- Increase wait time by 30-60 minutes
- Risk of fungal issues if overwatered

## **Warning Signs to Watch**

### **Overwatering Signs**
- Yellowing leaves on lower parts of plants
- Musty smell from growing medium
- Slow growth despite good conditions
- **Action**: Increase wait time or reduce duration

### **Underwatering Signs**
- Wilting during peak light hours
- Stunted growth
- Dry growing medium
- **Action**: Decrease wait time or increase duration

## **Your Current Configuration Issue**

❌ **Problem**: Your operational values are set to `00:00:00` (DISABLED)
```ini
sprinkler_on_duration = 01:10:00, 00:00:00    # DISABLED!
sprinkler_wait_duration = 03:00:00, 00:00:00   # DISABLED!
```

✅ **Fix**: Set operational values (second values) for your growth stage:

## **Recommended Fix for Your Setup**

Update your `device.conf` to:

```ini
[Sprinkler]
sprinkler_on_duration = 01:10:00, 00:03:00    # 3 minutes
sprinkler_wait_duration = 03:00:00, 03:00:00   # 3 hours
```

This provides:
- **Adequate moisture** for pea shoot germination
- **Sufficient water** for young tomatoes/peppers  
- **8 cycles per day** = balanced approach
- **Safe timing** that prevents overwatering

## **Testing Your New Schedule**

1. **Update device.conf** with recommended values
2. **Run validation**: `python3 quick_sprinkler_test.py`
3. **Monitor plants** for first 24-48 hours
4. **Adjust based on plant response**

## **Pro Tips**

1. **Morning Priority**: Ensure first cycle runs around 6-7am when plants start photosynthesis
2. **Evening Cutoff**: Last cycle should be before 9pm to avoid overnight moisture issues
3. **Growth Monitoring**: Take photos daily to track growth response to watering changes
4. **Medium Check**: Stick finger into growing medium - should be moist but not soggy
5. **Root Health**: Healthy roots are white/cream colored, not brown or slimy
