# ConfigLabs + RackTrack di satu VPS

Panduan memindahkan **configlabs.online** (Flask) dan **racktrack.online** (Next.js) dari Vercel ke satu VPS (Biznet Gio, Ubuntu 24.04).

```
configlabs.online ─┐                 ┌─ file statis + gunicorn 127.0.0.1:8000 (Flask)
                   ├─ nginx (HTTPS) ─┤
racktrack.online ──┘                 └─ next start 127.0.0.1:3000 (+ timer digest harian)
```

| Di Vercel | Di VPS |
|---|---|
| `vercel.json` rewrites, redirects, headers | `nginx/configlabs.online.conf` |
| Serverless function Flask | `systemd/configlabs.service` (gunicorn) |
| Next.js | `systemd/racktrack.service` (`next start`) |
| Vercel Cron `/api/cron/digest` 00:00 UTC | `systemd/racktrack-digest.timer` |
| Environment Variables | `/etc/configlabs.env`, `/etc/racktrack.env` |
| Auto-deploy dari GitHub | `.github/workflows/deploy-vps.yml` di kedua repo |

## 0. Buat VPS

Di Biznet Gio: **Ubuntu 24.04**, minimal **2 vCPU / 4 GB RAM** (build Next.js butuh RAM; script juga menambah swap 2 GB). Pasang SSH key saat membuat VPS, lalu catat IP publiknya.

## 1. Jalankan setup (pertama kali)

```bash
ssh root@IP_VPS          # atau user lain dengan sudo
git clone https://github.com/NaufalBudiman/ConfigLabs.git /tmp/configlabs
sudo bash /tmp/configlabs/server/setup-server.sh
```

Script ini memasang nginx, Python, Node.js 20, firewall (hanya port 22, 80, 443), membuat user `configlabs`, `racktrack` dan `deploy`, meng-clone kedua repo ke `/srv`, dan membuat file env kosong. Aman dijalankan berulang kali.

## 2. Isi environment variables

Cara paling mudah, satu perintah:

```bash
sudo fill-env
```

- Secret buatan aplikasi (`SESSION_SECRET`, `JWT_SECRET`, `AUTH_SECRET`, `CRON_SECRET`) dibuat acak otomatis di server. Hanya dibuat kalau masih kosong, jadi menjalankannya lagi tidak men-logout siapa pun. Konsekuensi satu kali: user yang login di Vercel harus login ulang.
- Kredensial dari layanan lain ditanyakan satu per satu dengan input tersembunyi (tidak tampil di layar, tidak masuk riwayat shell): `DATABASE_URL`, Google client ID/secret, `RESEND_API_KEY` (opsional). Ambil nilainya dari Neon, Google Cloud Console dan Resend, atau dari Vercel (**Settings → Environment Variables**, ikon mata).
- Kalau dua aplikasi memakai satu Google client, jawab `y` saat ditanya "use the same Google client".
- `sudo fill-env --check` menampilkan variabel yang sudah terisi dan yang belum (hanya nama). `sudo fill-env racktrack` hanya satu file. `--force` mengulang pertanyaan kredensial.
- `AUTH_URL=https://racktrack.online` dan `AUTH_TRUST_HOST=true` sudah terisi di `/etc/racktrack.env`; biarkan.

Mengedit manual juga bisa (`sudo nano /etc/configlabs.env`); tulis nilai sebagai `NAMA='nilai'` supaya karakter seperti `&` aman. Kalau secret diganti manual, `SESSION_SECRET` dan `JWT_SECRET` yang sama dengan di Vercel akan mempertahankan login user.
- **Database:** RackTrack memakai Neon, jadi datanya tetap di sana. Cek ke mana `DATABASE_URL` ConfigLabs mengarah. Kalau database itu ikut terkunci karena masalah billing Vercel, data perlu di-export (`pg_dump`) ke Postgres lain dulu.
- Jangan kirim isi file ini lewat chat atau commit ke git.

Lalu jalankan setup sekali lagi; kali ini kedua aplikasi di-build dan dinyalakan:

```bash
sudo bash /tmp/configlabs/server/setup-server.sh
```

Cek dari dalam server (sebelum DNS dipindah):

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: configlabs.online' http://127.0.0.1/      # 200
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: configlabs.online' http://127.0.0.1/vendors  # 200
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: racktrack.online'  http://127.0.0.1/      # 200 / 307
```

## 3. Pindahkan DNS (Hostinger)

Ubah **A record** `configlabs.online` dan `racktrack.online` (dan `www` kalau dipakai) dari IP Vercel (`216.198.79.1`) ke **IP VPS**. Hapus record AAAA/CNAME lama yang mengarah ke Vercel. Tunggu sampai `dig +short configlabs.online` menunjukkan IP VPS.

## 4. HTTPS (Let's Encrypt)

```bash
sudo certbot --nginx -d configlabs.online -d racktrack.online --redirect
# kalau www punya DNS juga:  -d www.configlabs.online -d www.racktrack.online
```

Sertifikat diperpanjang otomatis oleh timer certbot.

## 5. Login Google

Domain tidak berubah, jadi redirect URI di Google Cloud Console tetap berlaku. Pastikan masih ada:

- `https://configlabs.online/auth/google/callback`
- `https://racktrack.online/api/auth/callback/google`

## 6. Auto-deploy dari GitHub

Di Mac (bukan di server):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/configlabs_deploy -N "" -C "github-actions-deploy"
cat ~/.ssh/configlabs_deploy.pub     # salin
ssh-keyscan -t ed25519 IP_VPS        # salin hasilnya
```

Di server, tempel public key tadi ke `/home/deploy/.ssh/authorized_keys`. User `deploy` hanya boleh menjalankan `/usr/local/bin/deploy-configlabs` dan `/usr/local/bin/deploy-racktrack` lewat sudo.

Di **kedua** repo GitHub, **Settings → Secrets and variables → Actions**, tambahkan:

| Secret | Isi |
|---|---|
| `VPS_HOST` | IP VPS |
| `VPS_SSH_KEY` | isi `~/.ssh/configlabs_deploy` (private key) |
| `VPS_KNOWN_HOSTS` | hasil `ssh-keyscan` di atas |

Setelah itu setiap push ke `main` otomatis: pull, build (RackTrack), restart, lalu cek apakah aplikasinya hidup. Deploy manual juga bisa: `sudo deploy-configlabs` atau `sudo deploy-racktrack` di server.

## 7. Matikan Vercel

Setelah semuanya jalan di VPS: di Vercel, **Settings → Git → Disconnect** untuk kedua proyek (atau hapus proyeknya), supaya tidak ada tagihan atau deploy ganda.

## Perintah berguna

```bash
systemctl status configlabs racktrack            # status
journalctl -u configlabs -f                      # log ConfigLabs
journalctl -u racktrack -f                       # log RackTrack
systemctl list-timers racktrack-digest.timer     # jadwal digest
sudo systemctl start racktrack-digest.service    # kirim digest sekarang
sudo nginx -t && sudo systemctl reload nginx     # setelah ubah config nginx
```
