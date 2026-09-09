# 🚀 Vercel Par 24/7 Host Karne Ka Tareeka (Step-by-Step)

Maine poora project Vercel Serverless ke liye configure karke `vercel_app` folder me ready kar diya hai!

---

## 🌟 Tareeka 1: Terminal Se Direct Deploy (1 Command)

Terminal me `PC TO MOBILE` directory me yeh command chalayein:

```bash
./deploy_to_vercel.sh
```

### Kya hoga:
1. Yeh aapse **Vercel Login** karne ko kahega (Browser me "Confirm Email" / GitHub click karna hoga).
2. Project name puchega (Enter daba dein).
3. **20-30 seconds me live ho jayega** aur aapko permanent URL mil jayega:
   👉 `https://airlink-xxxx.vercel.app`

---

## 🌟 Tareeka 2: GitHub Ke Through Vercel Dashboard Se (Subway/Simple)

1. [GitHub.com](https://github.com) par ek naya repository banayein: `airlink-vercel`.
2. Terminal me yeh 2 commands chala kar push kar dein:
   ```bash
   cd "/home/nee/Desktop/PC TO MOBILE/vercel_app"
   git remote add origin https://github.com/<aapka-username>/airlink-vercel.git
   git push -u origin master
   ```
3. [Vercel.com](https://vercel.com) par jayein $\rightarrow$ **"Add New Project"** $\rightarrow$ GitHub repository select karein $\rightarrow$ **Deploy** button dabayein!
4. Aapka URL ready ho jayega: `https://airlink-xxxx.vercel.app`.

---

## 🔗 Phone Aur Kali PC Se Kaise Link Karein?

Deploy hone ke baad jo URL milega:
1. **Phone Me**: Wahi URL kholein (`https://airlink-xxxx.vercel.app`) aur **"Add to Home Screen"** kar lein. Phone chahe 4G/5G par ho ya duniya me kahi bhi, 24/7 khulega!
2. **PC Me**: PC on hote hi saari files automatically `/home/nee/Desktop/PC TO MOBILE/received_files/` folder me aane ke liye yeh command chala dein:
   ```bash
   ./setup_cloud_sync.sh https://airlink-xxxx.vercel.app
   ```
