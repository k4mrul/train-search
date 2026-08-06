Run this script in every day for next available date. At 7:55 AM

Terminal 1:
```
mkdir -p /tmp/chrome-reserve-profile
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-reserve-profile
```
Now login first. Now in console
```
Object.entries(localStorage)   #dump all info
localStorage.getItem('token')  #get current token. Paste below step
```

Terminal 2:
```
export TOKEN=""
python train_reserve_browser.py --cdp-port 9222 --from Dhaka --to "Cox's Bazar" --doj 17-Aug-2026 --train "COXS BAZAR EXPRESS (814)" --seats 2 --keep-open --continue
```

Above command will try to book train ticket for day 17. 




