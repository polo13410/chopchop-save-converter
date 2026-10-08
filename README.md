# Chop Chop Inc : convertisseur de sauvegarde démo vers jeu complet

Projet perso pour récupérer la progression de la démo de Chop Chop Inc. dans le jeu complet.
Officiellement, les sauvegardes de la démo ne sont pas compatibles.

## Où sont les sauvegardes

```
%USERPROFILE%\AppData\LocalLow\NullRef Entertainment\ChopChopIncDemo\saves\save0.sav
%USERPROFILE%\AppData\LocalLow\NullRef Entertainment\ChopChopInc\saves\save0.sav
```

Avant toute modification, copie ces dossiers ailleurs.
Pense aussi à désactiver Steam Cloud pour le jeu pendant les essais, sinon il peut écraser les fichiers.

## Format

Les sauvegardes utilisent le format binaire d'[Odin Serializer](https://github.com/TeamSirenix/odin-serializer).
Le module `odin_binary.py` le lit et l'écrit sans perte : décoder puis réencoder redonne exactement le même fichier.

Particularités observées dans ce jeu :
- toutes les chaînes sont en UTF-16 ;
- il n'y a pas de marqueur de fin de flux ;
- la racine est un `Service.SessionData.ServiceData` qui contient un dictionnaire type de service vers données.

## Utilisation

Nécessite Python 3.10 ou plus récent, sans dépendance.

```
python savetool.py check    save0.sav               # vérifie l'aller-retour sans perte
python savetool.py decode   save0.sav save0.json    # sauvegarde -> JSON éditable
python savetool.py encode   save0.json save0.sav    # JSON -> sauvegarde
python savetool.py summary  save0.sav --depth 3     # arborescence
python savetool.py services demo.sav complet.sav    # compare les services de deux sauvegardes
python savetool.py schema --a demo.sav --b c1.sav c2.sav  # compare les champs écrits par type
```

## Catalogue des identifiants

Les sauvegardes ne désignent les recettes, objets, missions, etc. que par un entier (assetID).
`extract_catalog.py` retrouve le nom de chaque ID dans les fichiers du jeu :

```
python -m venv .venv
.venv/Scripts/python -m pip install UnityPy
.venv/Scripts/python extract_catalog.py "C:/Program Files (x86)/Steam/steamapps/common/ChopChopIncDemo/ChopChopIncDemo_Data" catalog/demo.csv
.venv/Scripts/python extract_catalog.py "C:/Program Files (x86)/Steam/steamapps/common/ChopChopInc/ChopChopInc_Data" catalog/complet.csv
```

Résultat sur une sauvegarde de démo de trois heures : tous les IDs utilisés existent aussi dans le jeu complet,
avec le même sens. Seule exception : un panneau propre à la démo (`HiddenMission_HomeSweetHome_26_DEMOSIGN`).
La carte est aussi la même : la plupart des objets du décor ont le même type à la même position.

## Analyse de la structure (démo vs jeu complet)

Comparaison faite avec `savetool.py schema` sur une sauvegarde démo de trois heures
et trois sauvegardes du jeu complet, de 5 à 40 minutes de jeu.

**Structure des données.** Les types communs aux deux versions ont exactement les mêmes champs.
Seule différence réelle : `Inventory.Inventory` gagne un champ `totalAmount`, qui est la somme du contenu.
Le jeu complet ajoute des systèmes absents de la démo : IA des créatures, succès, améliorations de session,
interface, point de réapparition, nouveaux types de conditions de mission. Ils peuvent rester à leur état par défaut.

**Deux sortes d'identifiants.**
- Les *assetID* désignent un type de chose : recette, objet, mission, audience. Ils sont stables entre les versions.
  Les services Recipe, Shop, MissionBoard (débloquées), TargetAudience et le contenu des inventaires
  n'utilisent que ceux-là, et se copient donc tels quels.
- Les *worldObjectID* numérotent les objets présents dans le monde. Le jeu les attribue au chargement,
  donc ils **ne sont pas stables** : le même numéro désigne des objets différents dans les deux versions.
  Les données par objet (santé, machines, inventaires posés, spawners) et les missions en cours y sont rattachées.

**Les missions sont des objets du monde.** Chaque mission active existe comme objet, avec l'état de ses conditions.
Une mission terminée disparaît du monde. `MissionBoard.runningMissions` contient des worldObjectID.

**Correspondance des objets.** En comparant type et position arrondie, environ 77 % des objets de la démo
se retrouvent dans le jeu complet. Le reste : objets ramassés ou lâchés, animaux qui bougent,
arbres repoussés, constructions du joueur et quelques déclencheurs déplacés entre les versions.

## Stratégie de conversion envisagée

1. Partir d'une sauvegarde du jeu complet comme base.
2. Copier les services à assetID : recettes, boutique, missions débloquées, audiences, contenu des inventaires.
3. Pour les objets du monde : retrouver chaque objet de la démo dans la base par type et position,
   supprimer ceux que le joueur a détruits, ajouter ceux qu'il a construits avec de nouveaux worldObjectID.
4. Renuméroter toutes les données par objet et les missions en cours avec la table de correspondance.

## Conversion

```
python convert.py demo.sav base_complet.sav sortie.sav               # progression + carte
python convert.py demo.sav base_complet.sav sortie.sav --sans-monde  # progression seulement
```

`base_complet.sav` est une sauvegarde du jeu complet en tout début de partie.

**Progression** : recettes, articles de boutique, audiences, argent et sac du joueur, tableau des missions
et missions actives avec l'état de leurs conditions.
Une mission dont les conditions ont changé entre les versions repart de zéro.

**Carte** (`world.py`) : les numéros d'objets diffèrent entre les versions, les objets sont donc reconnus par type et position.
Dans une même version, les objets placés dans les scènes ont un numéro fixe : le jeu les retrouve par ce numéro
au chargement. Le convertisseur garde donc le numéro du jeu complet et n'y copie que l'état de la démo.
L'état initial des deux cartes est extrait des scènes du jeu par `extract_scene.py`.
- Les objets de la carte de la démo encore présents dans le jeu complet prennent leur état de la démo :
  arbre coupé, machine posée, téléporteur réparé.
- Le nouveau contenu du jeu complet est gardé.
- Les objets déplacés par les développeurs (jusqu'à 3 m) restent à leur nouvelle place, sauf s'ils ont été détruits dans la démo.
- Les objets apparus pendant la partie démo (constructions, bâtiments de la ville, objets lâchés) sont ajoutés.
- Les liens entre objets sont renumérotés : inventaires, machines, objets enfants des missions.
- Les machines automatisées du jeu complet (ex. atelier du castor) reçoivent une file de fabrication vide :
  sans données, elles font planter le chargement.
- Le joueur reprend sa position et son regard de la démo.

- Le joueur garde sa force, son endurance et sa vitesse, dans les limites du jeu complet.

Non transférés : objet en main, drones et camions en cours de livraison, succès.

Pour régénérer l'état initial des cartes :

```
.venv/Scripts/python extract_scene.py ".../ChopChopIncDemo_Data" catalog/scene-demo.csv
.venv/Scripts/python extract_scene.py ".../ChopChopInc_Data" catalog/scene-complet.csv
```

**Cycle de vie des missions**, observé sur une partie du jeu complet :
une mission active est un objet du monde, placé à l'origine, qui ne porte que le composant mission.
Une mission terminée disparaît. Le tableau garde les missions débloquées et disponibles par assetID,
et les missions en cours par worldObjectID.

**Codes de composants** (`serializedComponents`), identiques dans les deux versions :
2 santé, 3 inventaire, 4 déplacement sur spline, 7 spawner, 9 fabrication automatique,
10 fabrication, 15 ramassable, 17 mission, 25 IA (jeu complet), 29 réapparition (jeu complet).

## Avancement

- [x] Décodeur / encodeur Odin binaire, testé sur les deux sauvegardes
- [x] Vérifier que les identifiants d'objets et de recettes sont les mêmes entre démo et jeu complet
- [x] Comparer la structure interne des données par type
- [x] Comprendre les deux sortes d'identifiants et le rattachement des missions
- [x] Comprendre le cycle de vie des missions
- [x] Décoder `serializedComponents` des objets du monde
- [x] Convertisseur version 1 : progression sans le monde
- [x] Tester la version 1 en jeu : la sauvegarde se charge et la progression est là
- [x] Version 2 : objets du monde et position du joueur
- [ ] Tester la version 2 en jeu

## Différences connues entre les versions

| Seulement dans la démo | Seulement dans le jeu complet |
|---|---|
| DeliveryDrone, Truck, MoveOnSpline | Achievement, SessionUnlock, UI |
| | AIBrain, PlayerRespawn, nouveaux types de missions |
