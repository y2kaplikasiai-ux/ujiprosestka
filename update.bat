@echo off
echo Menghentikan kontainer lama...
docker stop kontainer-tka
docker rm kontainer-tka

echo Mengambil kode terbaru dari GitHub...
git pull

echo Membangun ulang Docker image...
docker build -t app-tka .

echo Menjalankan kontainer baru...
docker run -d -p 8501:8501 --name kontainer-tka app-tka
echo Update selesai dan aplikasi siap!
pause