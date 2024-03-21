const fs = require('fs');
const initSqlJs = require('sql.js');

const filebuffer = fs.readFileSync('db.sqlite');

function query(db, stmt) {
  res = db.exec(stmt)[0]
  return res.values.map((row) => Object.fromEntries(res.columns.map((colname, index) => ([colname, row[index]]))))
}

function get_procedures(db) {
  return query(db, 'SELECT title, reference FROM procedures')
}

function get_votes(db, reference) {
  stmt = `
      SELECT id, title, amendment_id
      FROM votes
      WHERE procedure_ref='${reference}'
    `
  return query(db, stmt)
}

const arr = initSqlJs().then(function(SQL) {
  const db = new SQL.Database(filebuffer);
  const procedures = get_procedures(db)
    .map((proc) => ({ votes: get_votes(db, proc.reference), ...proc }))
  return procedures
})

module.exports = arr