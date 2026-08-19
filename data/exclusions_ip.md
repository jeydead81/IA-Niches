# Exclusions IP / marques — low-content

Une entrée par ligne. Casse et accents indifférents (le filtre dépouille les deux).
Les lignes vides et celles commençant par `#` sont ignorées.

Ce fichier est le SEUL garde-fou juridique du dépôt. Les autres filtres protègent un
chiffre ; celui-ci protège le compte KDP. Un cahier de coloriage sous marque n'est pas
une niche médiocre — c'est un retrait de publication, et répété, une fermeture de compte.
L'autocomplete en est plein : c'est exactement ce que les gens tapent, donc ce que l'arbre
remonte en premier.

Le filtre compare des MOTS ENTIERS. Ne pas ajouter d'entrée de moins de trois lettres
sans vérifier : un terme trop court écarte des niches valables en silence, avant toute
mesure, et rien en aval ne peut le rattraper.

### Termes RETIRÉS après mesure — ne pas les remettre

Ces entrées rejetaient des niches parfaitement légitimes, **en silence et avant toute
mesure**. Un rejet muet ne se remarque pas : il a fallu passer 121 requêtes valables au
filtre pour les voir.

Règle appliquée, et elle se pèse à chaque fois : on **retire** un terme dont l'usage
légitime est une *catégorie courante* du low-content ; on le **garde** quand l'usage
légitime est *incident*.

- **`bts`** — c'est d'abord un diplôme français. « cahier de révision BTS MCO », « carnet
  de bord BTS communication » : les cahiers de révision sont une catégorie entière du
  rayon. Le groupe reste couvert par `bangtan boys`.
- **`puma`** — c'est d'abord un animal, et le coloriage animalier est une des plus grosses
  catégories du low-content. La marque de sport est perdue : arbitrage assumé.

### Termes AMBIGUS conservés — arbitrage inverse

- **`nike`** — la déesse grecque existe (« coloriage mythologie grecque Nike déesse »),
  mais c'est un usage *incident* ; les carnets sous marque de sport sont un risque réel.
- **`ferrari`** — patronyme italien courant (« livre d'or famille Ferrari »), même
  raisonnement.

Ces deux-là écartent donc quelques niches valables. C'est un coût accepté, pas un oubli.

### Sigles volontairement ABSENTS — ne pas les ajouter « par cohérence »

- **`om`** (Olympique de Marseille) : « om » est aussi le mantra. « carnet de méditation
  om », « journal de yoga om » sont des niches parfaitement valables, et elles seraient
  rejetées en silence. L'entrée `olympique de marseille` couvre le club sans ce risque.
- **`dc`**, **`mu`**, **`jo`** : deux lettres, même problème. Les formes longues
  (`dc comics`, `manchester united`, `jeux olympiques`) sont déjà dans la liste.

`psg` a été ajouté après vérification : trois lettres, et aucun mot français courant du
low-content ne le contient comme mot entier.

## Personnages et franchises jeunesse
disney
pixar
mickey
minnie
la reine des neiges
frozen
elsa
raiponce
vaiana
stitch
winnie l'ourson
pat patrouille
paw patrol
peppa pig
t'choupi
petit ours brun
sam le pompier
bluey
gabby et la maison magique
miraculous
ladybug
barbapapa
oui-oui
masha et michka
pyjamasques
les schtroumpfs
astérix
obélix
tintin
lucky luke
titeuf
boule et bill
cédric
le petit nicolas
martine
babar
caillou
dora l'exploratrice
pokemon
pikachu
digimon
yu-gi-oh
beyblade
hello kitty
sanrio
my little pony
barbie
bratz
lol surprise
polly pocket
playmobil
lego
duplo
bakugan
sonic
mario
luigi
zelda
kirby
pac-man

## Films, séries, univers
harry potter
poudlard
hogwarts
le seigneur des anneaux
hobbit
star wars
mandalorian
marvel
avengers
spider-man
spiderman
iron man
hulk
captain america
black panther
batman
superman
wonder woman
justice league
dc comics
jurassic park
transformers
gremlins
ghostbusters
retour vers le futur
stranger things
wednesday
mercredi addams
la casa de papel
game of thrones
squid game
scooby-doo
les minions
moi moche et mechant
shrek
madagascar
kung fu panda
toy story
cars disney
nemo
le roi lion

## Manga et animation japonaise
one piece
naruto
dragon ball
goku
demon slayer
kimetsu
jujutsu kaisen
my hero academia
attack on titan
l'attaque des titans
sailor moon
totoro
ghibli
studio ghibli
death note
bleach
fairy tail
hunter x hunter
tokyo ghoul
spy x family
chainsaw man

## Jeux vidéo et plateformes
minecraft
fortnite
roblox
among us
call of duty
gta
grand theft auto
league of legends
overwatch
valorant
animal crossing
splatoon
nintendo
playstation
xbox

## Sport — clubs, ligues, personnalités
paris saint-germain
psg
olympique de marseille
olympique lyonnais
real madrid
fc barcelone
manchester united
liverpool fc
juventus
bayern munich
ligue 1
premier league
champions league
coupe du monde fifa
fifa
uefa
nba
nfl
tour de france
roland-garros
jeux olympiques
mbappe
messi
ronaldo
zidane

## Marques et produits
coca-cola
mcdonald's
nutella
kinder
haribo
nike
adidas
chanel
louis vuitton
gucci
apple iphone
samsung galaxy
netflix
tiktok
instagram
youtube
spotify
harley-davidson
ferrari
lamborghini
porsche
tesla

## Musique et célébrités
taylor swift
beyonce
rihanna
billie eilish
blackpink
k-pop bts
stromae
aya nakamura
johnny hallyday
elvis presley
the beatles
rolling stones
michael jackson

## Ajouts du 2026-08-19 — issus d'un corpus adversarial de 198 requêtes

Le filtre les laissait TOUTES passer. Deux causes distinctes : des formes mutées
(pluriel, trait d'union, apostrophe, agglutination), traitées depuis dans le
matcher lui-même ; et des termes réellement absents, listés ici.

Les fautes d'orthographe courantes (« pikatchu », « addidas », « nutela ») sont
incluses quand elles sont fréquentes. La couverture n'est PAS exhaustive et ne peut
pas l'être : le filtre est une première ligne, jamais une garantie juridique.

### Formes séparées de marques écrites en un mot
bat man
mine craft
play station
x box
over watch
bey blade
tik tok
black pink
fort nite
lady bug
mc donald
you tube
insta gram
pac man

### Produits dérivés et déclinaisons
legoland
disneyland
super mario
mario kart
mario bros
gta 5
gta v
jurassic world
star wars
marvel comics

### Personnages — jeunesse et animation
winnie
dora
peppa
mon petit poney
pj masks
gabby dollhouse
masha
michka
simba
buzz l'eclair
moi moche et mechant
barbapapa
schtroumpf
pyjamasque
minion

### Personnages — manga et animation japonaise
luffy
sangoku
son goku
vegeta
tanjiro
nezuko
pikatchu
boku no hero academia
shingeki no kyojin
kimetsu no yaiba
one peace
le voyage de chihiro
chihiro
princesse mononoke

### Personnages et lieux — films et séries
dark vador
bebe yoda
grogu
gryffondor
serpentard
poufsouffle
serdaigle
lord of the rings
terre du milieu
l'homme araignee
gotham
jurassic parc
la famille addams
mercredi adams
casa del papel
le trone de fer

### Sport — formes courantes
paris sg
real de madrid
fc barcelona
ligue des champions
jo paris 2024
coupe du monde de football
cr7
neymar

### Marques — formes courtes et graphies courantes
mcdo
coca
addidas
lambo
nutela
iphone
ps5
ps4
nintendo switch

### Musique — formes courantes
bangtan boys
swifties
eras tour
mickael jackson
johnny halliday

### Complements — seconde passe de mesure

picachu
packman
fortnight
roblocks
sonik
barca
youtubeur
insta
vuitton
gabby
dollhouse
