const fs = require('fs');
const initSqlJs = require('sql.js');

const filebuffer = fs.readFileSync('db.sqlite');

function query(db, stmt) {
  res = db.exec(stmt)[0]
  return res.values.map((row) => Object.fromEntries(res.columns.map((colname, index) => ([colname, row[index]]))))
}

function get_members(db) {
  return query(db, 'SELECT * FROM members')
}

const arr = initSqlJs().then(function(SQL) {
  const db = new SQL.Database(filebuffer);
  const members = get_members(db)
  return members
})

module.exports = arr