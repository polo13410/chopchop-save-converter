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
```

## Avancement

- [x] Décodeur / encodeur Odin binaire, testé sur les deux sauvegardes
- [ ] Cartographier chaque service (argent, inventaire, recettes, objets du monde, missions)
- [ ] Vérifier que les identifiants d'objets et de recettes sont les mêmes entre démo et jeu complet
- [ ] Greffer les sections compatibles de la démo dans une sauvegarde du jeu complet
- [ ] Tester en jeu, une section à la fois

## Différences connues entre les versions

| Seulement dans la démo | Seulement dans le jeu complet |
|---|---|
| DeliveryDrone, Truck, MoveOnSpline | Achievement, SessionUnlock, UI |
| | AIBrain, PlayerRespawn, nouveaux types de missions |
