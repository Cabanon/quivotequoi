const mongoose = require('mongoose');
const { Member, Vote } = require("./models");

main().catch(err => {console.log(err)});

function normalizeParty(str) {
    switch (str) {
        case "Agir - La Droite constructive":
        case "Liste Renaissance":
        case 'La République en marche':
        case "Liste L'Europe Ensemble":
            return 'Renaissance'
        case 'Mouvement Radical Social-Libéral':
            return 'Parti Radical'
        default:
            return str
    }
}

async function main() {
    await mongoose.connect('mongodb://127.0.0.1:27017/quivotequoi');
    const db = mongoose.connection.getClient().db('quivotequoi')

    await Member.collection.drop()
    let members = await db.collection('raw_meps')
        .find({ 
            active: true,
            Constituencies: { $elemMatch : { term: 9, country: 'France' } }
        })
        .toArray()
    members = members
        .map((member) => ({
            id: member.UserID,
            full_name: member.Name.full,
            party: normalizeParty(member.Constituencies.find((con) => con.term === 9).party)
        }))
    await Member.insertMany(members)
    
    const startDate = new Date(2019, 7, 2)
    await Vote.collection.drop()
    let votes = await db.collection('raw_votes')
        .find({ 
            epref: { $exists: true },
            votes: { $exists: true },
            ts: { $gt: startDate.toISOString() }
        })
        .toArray()
    votes = votes
        .map((vote) => ({
            id: vote.voteid,
            title: vote.title,
            reference: Array.isArray(vote.epref) ? vote.epref[0] : vote.epref,
            positions: Object.entries(vote.votes).flatMap(([position, { groups }]) => Object.values(groups).flat().map(({ mepid }) => ({ position, mepid }))),
        }))
    await Vote.insertMany(votes)
    console.log('yay')
    
    await mongoose.disconnect()
}