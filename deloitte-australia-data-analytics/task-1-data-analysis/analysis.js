// Down time analysis for Daikibo's telemetry (daikibo-telemetry-data.json).
// Each machine sends a status every 10 minutes, so every "unhealthy" status
// counts as 10 minutes of potential down time (the "Unhealthy" measure).
//
// Usage: node analysis.js daikibo-telemetry-data.json

const fs = require('fs')

const records = JSON.parse(fs.readFileSync(process.argv[2] || 'daikibo-telemetry-data.json', 'utf8'))

const perFactory = {}
const perFactoryAndType = {}

for (const r of records) {
  if (r.data.status !== 'unhealthy') continue
  const factory = r.location.factory
  const key = `${factory} | ${r.deviceType}`
  perFactory[factory] = (perFactory[factory] || 0) + 10
  perFactoryAndType[key] = (perFactoryAndType[key] || 0) + 10
}

const sortDesc = (obj) => Object.entries(obj).sort((a, b) => b[1] - a[1])

console.log(`Messages: ${records.length}`)
console.log('\nDown time per factory (minutes):')
for (const [k, v] of sortDesc(perFactory)) console.log(`  ${k.padEnd(24)} ${v}`)
console.log('\nDown time per factory and device type (minutes):')
for (const [k, v] of sortDesc(perFactoryAndType)) console.log(`  ${k.padEnd(40)} ${v}`)
