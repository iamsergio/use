activeTerminalId=`qdbus org.kde.yakuake /yakuake/sessions org.kde.yakuake.activeTerminalId`
qdbus org.kde.yakuake /yakuake/tabs org.kde.yakuake.setTabTitle $activeTerminalId $1
