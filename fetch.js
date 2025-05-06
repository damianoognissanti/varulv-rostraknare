const fs = require('fs');
const https = require('https');
const base = 'https://www.rollspel.nu/threads/bh-ii-r1.85315/';
const maxPages = 10;

function fetchPage(page, callback) {
  const url = page === 1 ? base : `${base}page-${page}`;
  https.get(url, res => {
    let data = '';
    res.on('data', chunk => data += chunk);
    res.on('end', () => {
      fs.writeFileSync(`data/page${page}.html`, data);
      console.log(`Sida ${page} sparad.`);
      callback();
    });
  }).on('error', err => {
    console.error('Fel vid hämtning:', err.message);
    callback();
  });
}

function run(p = 1) {
  if (p > maxPages) return;
  fetchPage(p, () => run(p + 1));
}

run();
