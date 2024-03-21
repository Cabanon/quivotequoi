for data in meps dossiers plenary_amendments votes
do  
    file="ep_$data.json.lz"
    if ! curl -o $file -z $file https://parltrack.org/dumps/$file -v --stderr - | grep -q 'not new enough'
    then
        lzip -c -d $file | mongoimport --db quivotequoi --collection raw_$data --jsonArray --drop
    fi
done