import folium

from folium import Map
from pydantic import BaseModel


class Point(BaseModel):
    latitude: float
    longitude: float


def get_folium_map(center_point: Point, points: list[Point], zoom_level: int = 14) -> Map:
    folium_map = folium.Map(
        location=[center_point.latitude, center_point.longitude], zoom_start=zoom_level)

    for point in points:
        folium.Marker(location=[point.latitude, point.longitude],
                      popup='Point').add_to(folium_map)

    return folium_map


point_1 = Point(latitude=33.89264295626195, longitude=-5.500305816538693)
point_2 = Point(latitude=33.899915132942326, longitude=-5.520818749583605)
point_3 = Point(latitude=33.891645357611154, longitude=-5.5397637571355105)
center_point = Point(latitude=33.89565560255, longitude=-5.522530349727877)

folium_map = get_folium_map(center_point, [point_1, point_2, point_3])
folium_map