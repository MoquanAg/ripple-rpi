# Your Optimized Watering Schedule

## ✅ **Configuration Applied Successfully**

Your sprinkler system is now configured with the **BALANCED** profile, optimized for your mixed plant setup:

```ini
[Sprinkler]
sprinkler_on_duration = 01:10:00, 00:03:00    # 3 minutes ON
sprinkler_wait_duration = 03:00:00, 03:00:00   # 3 hours WAIT
```

## 📊 **Your Active Schedule**

- **Watering Duration**: 3 minutes per cycle
- **Wait Between Cycles**: 3 hours  
- **Daily Cycles**: ~8 times per day
- **Total Daily Watering**: ~24 minutes
- **Typical Run Times**: 6am, 9am, 12pm, 3pm, 6pm, 9pm, 12am, 3am

## 🌱 **Why This Works for Your Plants**

### **Pea Shoots (Just Germinated)**
✅ **3-minute cycles**: Gentle enough to prevent seed displacement  
✅ **Every 3 hours**: Maintains consistent moisture for germination  
✅ **24 min/day total**: Adequate water without oversaturation

### **Tomatoes & Peppers (Young Plants)**  
✅ **3-minute cycles**: Sufficient water for substrate cups  
✅ **Every 3 hours**: Allows proper drainage between waterings  
✅ **8 cycles/day**: Meets water needs without root rot risk

## 📅 **Growth Stage Adjustments**

As your plants develop, you can easily adjust:

### **Week 1-2: Current Setup is Perfect**
- Pea shoots need frequent, gentle watering
- Young tomatoes/peppers establishing roots

### **Week 3-4: Consider "Germination" Profile** 
If pea shoots need more frequent watering:
```bash
python3 update_sprinkler_config.py germination
```
- 2 minutes every 2 hours (more frequent)

### **Week 5+: Switch to "Mature" Profile**
When tomatoes/peppers get larger:
```bash
python3 update_sprinkler_config.py mature  
```
- 4 minutes every 4 hours (longer, less frequent)

## 🔍 **What to Monitor**

### **First 48 Hours - Watch Closely**
- **Pea shoots**: Should stay moist but not waterlogged
- **Tomatoes/peppers**: Substrate should drain well between cycles
- **No wilting** during peak daylight hours
- **No yellowing** of lower leaves

### **Daily Checks**
1. **Morning (before first cycle)**: Check if medium is appropriately moist
2. **Midday**: Plants should look perky, not wilted
3. **Evening**: Medium should be moist but not soggy

### **Warning Signs**

❌ **TOO MUCH WATER**:
- Yellowing leaves (especially lower ones)
- Musty smell from growing medium  
- Slow/stunted growth
- **Fix**: Switch to "mature" profile (less frequent)

❌ **TOO LITTLE WATER**:
- Wilting during day (especially afternoon)
- Dry growing medium
- Stunted growth
- **Fix**: Switch to "germination" profile (more frequent)

## 🛠️ **Easy Adjustments**

### **If Plants Look Thirsty**
```bash
python3 update_sprinkler_config.py germination  # More frequent
```

### **If Plants Look Overwatered**  
```bash
python3 update_sprinkler_config.py mature       # Less frequent
```

### **For Quick Testing**
```bash
python3 update_sprinkler_config.py test         # 30sec every 2min
```

## 📈 **Expected Growth Timeline**

### **Week 1**: Pea shoots establish, tomatoes/peppers root development
### **Week 2**: Pea shoots ready for harvest, tomatoes/peppers first true leaves
### **Week 3**: New pea shoot cycle, tomatoes/peppers vegetative growth
### **Week 4+**: Focus shifts to tomatoes/peppers as main crop

## 🎯 **Success Metrics**

**Pea Shoots**:
- Ready to harvest in 7-14 days
- 2-4 inches tall with bright green leaves
- Crisp texture, sweet flavor

**Tomatoes/Peppers**:
- Strong root development in substrate
- New leaf growth every few days
- No nutrient deficiency signs

## 📞 **Quick Commands Reference**

```bash
# Check current status
python3 quick_sprinkler_test.py

# Run full system test  
./run_sprinkler_test.sh

# Change watering frequency
python3 update_sprinkler_config.py [germination|balanced|mature|test]

# View this guide
cat your_watering_schedule.md
```

## 🏆 **You're All Set!**

Your system is now configured optimally for your current plant mix. The balanced profile should work well for both plant types. Monitor plant response for the first few days and adjust if needed.

**Backup created**: `config/device.conf.backup_20250920_160611`  
**Configuration validated**: ✅ All systems go!

Happy growing! 🌱🍅🌶️
